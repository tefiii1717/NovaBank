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

## Orquestación (Tefi) — `services/saga-orquestada` (Prefect) + servicios de Cuentas y Riesgo

*(Sección a completar por Tefi con su implementación: cómo el flow de Prefect llama
explícitamente a cada `@task`, cómo se ve la ejecución en la UI de Prefect, y cómo
se disparan las compensaciones en orden inverso desde el propio flow cuando una
`task` falla.)*

## Conclusión comparativa

| Criterio | Coreografía (Yuly) | Orquestación (Tefi) |
|---|---|---|
| Acoplamiento | Bajo — solo al contrato de eventos | Alto — el orquestador conoce a todos los servicios |
| Punto único de fallo | No | Sí (si el orquestador cae a mitad de flujo) |
| Trazabilidad "de fábrica" | Baja — hay que construir un agregador propio | Alta — Prefect UI muestra el flujo completo |
| Control del orden de compensación | Implícito (cada servicio reacciona a lo que le corresponde) | Explícito (el flow decide y llama la reversa) |
| Curva para agregar un paso nuevo a la saga | Agregar un nuevo suscriptor sin tocar los demás | Modificar el flow central |
