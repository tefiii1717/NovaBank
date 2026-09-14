# Comparativa: Orquestación vs. Coreografía — NovaBank Saga

## Coreografía (Yuly) — implementada en `services/gateway-coreografia` + `services/pasarela-interbancaria`

**Cómo funciona en este repo:** no hay ningún componente que le diga a los demás qué
hacer. El `gateway-coreografia` solo hace dos cosas: publica el evento inicial
`TransferenciaSolicitada` en Redis, y mantiene un "read model" (tabla `historial`)
escuchando pasivamente TODOS los eventos del canal `saga.eventos` para poder
responder `GET /transferencia/{id}/estado` sin preguntarle a nadie más. La
`Pasarela Interbancaria` reacciona únicamente a `RiesgoAprobado`; no sabe que existe
un Gateway, un Riesgo o una Cuenta — solo conoce el contrato de eventos
(`docs/CONTRATO_EVENTOS.md`).

**Acoplamiento:** bajo. Se puede apagar la Pasarela y el resto de la saga (débito,
riesgo) sigue publicando sus eventos sin errores — simplemente la transacción se
queda en `EN_EJECUCION` hasta que la Pasarela vuelva a estar en línea y consuma el
evento pendiente. Ningún servicio importa código de otro; el único acoplamiento es
al **contrato de eventos**, versionado en un documento, no en una librería
compartida.

**Punto único de fallo:** no existe un orquestador central que, si se cae a mitad
de una transacción, deje a todos los servicios sin saber qué sigue. Cada servicio
decide su propia reacción de forma autónoma.

**Trazabilidad (el costo real de la coreografía):** este es el punto débil del
patrón, y lo confirmamos al construirlo: para poder responder "¿en qué va la
transacción X?" tuvimos que construir nosotros mismos un agregador
(`app/aggregator.py`) que reconstruye el estado leyendo la secuencia completa de
eventos — no hay un lugar único donde "está" el estado de la saga, hay que
derivarlo. Si dos servicios reaccionan al mismo evento con un pequeño desfase, el
orden de llegada al agregador no está garantizado en el mismo milisegundo, y para
depurar un caso raro hay que leer los logs de 3 servicios distintos en vez de mirar
una sola pantalla de flujo (como sí ofrece Prefect en el modo orquestado). Lo
resolvimos con el campo `contexto` (event-carried state transfer) propagado en
cada evento, para que ningún servicio necesite consultar a otro para saber qué
hacer — pero eso es una decisión de diseño que tuvimos que tomar explícitamente,
no algo que el patrón da gratis.

**Idempotencia:** se resuelve en dos capas — el Gateway no vuelve a publicar
`TransferenciaSolicitada` si el `idempotency_key` ya existe (CP-05), y cada
servicio reactivo (la Pasarela, por ejemplo) además marca en Redis
`procesado:{idempotency_key}:{tipo}` antes de actuar, por si el mismo evento
llegara duplicado por el bus.

## Orquestación (Sofía) — `saga-orchestrator/flows.py` (Prefect) + `services/accounts` y `services/risk`

**Cómo funciona en este repo:** hay un solo componente que sabe que existe una
"saga" — el `@flow saga_transferencia` en `saga-orchestrator/flows.py`. Cada paso
(`debitar_cuenta`, `validar_riesgo`, `liquidar_pasarela`, y sus reversas
`reversar_debito`/`anular_riesgo`) es un `@task` de Prefect que el flow llama
**explícitamente, por su nombre, en el orden que el flow decide**. `accounts`,
`risk` y `clearing-stub` no saben que son parte de una saga: son endpoints HTTP
sencillos (`/debitar`, `/validar-riesgo`, `/liquidar`, `/reversar`,
`/anular-riesgo`) que solo responden lo que se les pregunta. Todo el
conocimiento de "qué sigue si esto falla" vive en un único archivo.

**Acoplamiento:** alto. El flow importa/conoce las URLs de los tres servicios
(`ACCOUNTS_URL`, `RISK_URL`, `CLEARING_URL`) y arma él mismo cada payload HTTP.
Si `accounts` cambiara su endpoint de `/debitar` a otro nombre, el flow se
rompe — no hay una capa de indirección como el contrato de eventos de la
coreografía. Esto también se sintió al dockerizar todo: `flows.py` traía las
tres URLs hardcodeadas a `127.0.0.1`, que solo funcionan si el script corre en
la misma máquina que los tres servicios; para que corriera dentro de
`docker-compose` (cada servicio en su propio host de red) hubo que volverlas
configurables por variable de entorno. Es un síntoma típico de acoplamiento
fuerte: el orquestador necesita saber *dónde* vive cada servicio, no solo
*qué contrato* respeta.

**Punto único de fallo:** sí. Todo pasa por el proceso que ejecuta el `@flow`.
Si ese proceso muere entre `debitar_cuenta` y `validar_riesgo` (por ejemplo, el
contenedor se reinicia), la cuenta queda debitada y nadie — ni Prefect, ni los
servicios — sabe por su cuenta que hay que revertirla; a diferencia de la
coreografía, donde cada servicio reacciona sin depender de que un tercero siga
vivo. La ganancia a cambio es que, mientras el orquestador SÍ está vivo, el
control de la secuencia y de las compensaciones es explícito y centralizado —
no depende de que cada servicio "adivine" correctamente cuándo le toca actuar.

**Trazabilidad:** este es el punto fuerte del patrón, confirmado al construirlo
y correrlo: cada `@task` aparece como una unidad independiente en la UI de
Prefect (`http://localhost:4200`) con su propio estado (`Completed`/`Failed`) y
su tiempo de ejecución — incluido el `time.sleep(DELAY)` de 3 segundos por paso
que se usó para poder ver el avance con calma. No hace falta reconstruir nada:
Prefect ya sabe, por diseño, "en qué va" cada corrida del flow. El costo es que
esa trazabilidad vive *adentro* de un solo componente — si se quisiera exponer
el progreso paso a paso a un cliente externo (como el frontend), hay que
construir algo encima (ver `saga-orchestrator/api.py` más abajo), porque
Prefect por sí solo no expone HTTP para consultar el estado de una transacción
puntual.

**Control de compensación:** explícito y centralizado. En `saga_transferencia`,
cada paso está en su propio `try/except`, y el flow decide a mano qué reversar:
si `validar_riesgo` falla, llama `reversar_debito`; si `liquidar_pasarela`
falla, llama `anular_riesgo` y *después* `reversar_debito` (orden inverso
literal al de ejecución). No hay ambigüedad posible sobre qué se compensa y en
qué orden, porque está escrito en una sola función de arriba hacia abajo — la
contraparte de que la coreografía necesite un `contexto` propagado en cada
evento para que cada servicio "sepa" reaccionar solo.

**Exponerlo a un frontend:** `flows.py` originalmente se disparaba como script
de línea de comandos (`python flows.py <origen> <destino> <monto> <idem>
[--fraude] [--timeout]`), sin HTTP. `saga-orchestrator/api.py` lo envuelve con
el mismo contrato `POST /transferencia` / `GET /transferencia/{id}/estado` que
usa `gateway-coreografia`, corriendo el flow en un hilo de fondo y reconstruyendo
un `historial` a partir del resultado final (no hay eventos incrementales reales
como en Redis, así que los timestamps del timeline se interpolan entre el inicio
y el fin de la corrida) — para que el frontend pinte el mismo timeline sin que
le importe qué modo lo resolvió.

## Conclusión comparativa

| Criterio | Coreografía (Yuly) | Orquestación (Sofía) |
|---|---|---|
| Acoplamiento | Bajo — solo al contrato de eventos | Alto — el orquestador conoce a todos los servicios |
| Punto único de fallo | No | Sí (si el orquestador cae a mitad de flujo) |
| Trazabilidad "de fábrica" | Baja — hay que construir un agregador propio | Alta — Prefect UI muestra el flujo completo |
| Control del orden de compensación | Implícito (cada servicio reacciona a lo que le corresponde) | Explícito (el flow decide y llama la reversa) |
| Curva para agregar un paso nuevo a la saga | Agregar un nuevo suscriptor sin tocar los demás | Modificar el flow central |

## Hallazgo al construir ambos modos contra los mismos servicios

`accounts` y `risk` terminaron sirviendo **los dos modos con el mismo código de
negocio**: sus endpoints HTTP (`_debitar`, `_validar_riesgo`, `_reversar`,
`_anular_riesgo`) los sigue llamando el flow orquestado tal cual los escribió
Sofía, y encima se les agregó un listener de Redis (`redis_listener.py`) que
llama a esas mismas funciones cuando reacciona a `saga.eventos`. Ninguna de las
dos reglas de negocio (validar saldo, aplicar el límite diario, revertir un
débito) está duplicada — lo único que cambia entre modos es *quién dispara* esa
lógica: una llamada HTTP directa del flow, o un evento del bus. Esa separación
(lógica de dominio por un lado, forma de invocarla por otro) es en la práctica
lo que permitió comparar orquestación y coreografía de manera justa: la
diferencia observable entre los dos modos es puramente de coordinación, no de
qué hace cada servicio por dentro.
