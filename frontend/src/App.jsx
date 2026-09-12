import { useEffect, useRef, useState } from "react";
import { crearTransferencia, obtenerEstado } from "./api.js";
import { ESTADOS_CON_COMPENSACION_ESPERADA, ESTADOS_TERMINALES, MODOS } from "./constants.js";
import ModeSelector from "./components/ModeSelector.jsx";
import TransferForm from "./components/TransferForm.jsx";
import StatusTimeline from "./components/StatusTimeline.jsx";

const INTERVALO_POLLING_MS = 1500;
// RECHAZADO_RIESGO/RECHAZADO_RED son terminales de negocio, pero la
// CompensacionEjecutada que los sigue llega después por diseño (ver constants.js):
// seguimos consultando este tiempo extra para no cortar el polling antes de
// que la reversa aparezca en el historial.
const GRACIA_COMPENSACION_MS = 6000;

export default function App() {
  const [modo, setModo] = useState(MODOS.COREOGRAFIA);
  const [transaccion, setTransaccion] = useState(null);
  const [ultimaIdempotencyKey, setUltimaIdempotencyKey] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);
  const intervaloRef = useRef(null);

  function detenerPolling() {
    if (intervaloRef.current) {
      clearInterval(intervaloRef.current);
      intervaloRef.current = null;
    }
  }

  useEffect(() => detenerPolling, []);

  function iniciarPolling(modoActivo, idempotencyKey) {
    detenerPolling();
    let terminalDesde = null;
    intervaloRef.current = setInterval(async () => {
      try {
        const estado = await obtenerEstado(modoActivo, idempotencyKey);
        setTransaccion(estado);

        if (!ESTADOS_TERMINALES.has(estado.estado)) {
          return;
        }
        if (!ESTADOS_CON_COMPENSACION_ESPERADA.has(estado.estado)) {
          detenerPolling();
          setEnviando(false);
          return;
        }
        // Estado terminal que espera compensación: damos un margen antes de
        // dejar de consultar, para alcanzar a ver el paso "Compensado".
        if (terminalDesde === null) {
          terminalDesde = Date.now();
        } else if (Date.now() - terminalDesde >= GRACIA_COMPENSACION_MS) {
          detenerPolling();
          setEnviando(false);
        }
      } catch (err) {
        setError(err.message);
        detenerPolling();
        setEnviando(false);
      }
    }, INTERVALO_POLLING_MS);
  }

  async function manejarEnvio(datos) {
    setError(null);
    setEnviando(true);
    setTransaccion(null);
    try {
      const respuesta = await crearTransferencia(modo, datos);
      setUltimaIdempotencyKey(respuesta.idempotency_key);
      const estadoInicial = await obtenerEstado(modo, respuesta.idempotency_key);
      setTransaccion(estadoInicial);

      const yaResuelta =
        ESTADOS_TERMINALES.has(estadoInicial.estado) &&
        !ESTADOS_CON_COMPENSACION_ESPERADA.has(estadoInicial.estado);

      if (yaResuelta) {
        setEnviando(false);
      } else {
        iniciarPolling(modo, respuesta.idempotency_key);
      }
    } catch (err) {
      setError(err.message);
      setEnviando(false);
    }
  }

  function manejarCambioModo(nuevoModo) {
    detenerPolling();
    setModo(nuevoModo);
    setTransaccion(null);
    setError(null);
    setEnviando(false);
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-3xl space-y-6">
        <header>
          <h1 className="text-2xl font-bold text-slate-900">NovaBank International</h1>
          <p className="text-sm text-slate-500">
            Simulador de transferencias interbancarias — Patrón Saga (Coreografía vs. Orquestación)
          </p>
        </header>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Modo de ejecución de la Saga
          </h2>
          <ModeSelector modo={modo} onCambiar={manejarCambioModo} disabled={enviando} />
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Nueva transferencia
          </h2>
          <TransferForm
            onSubmit={manejarEnvio}
            disabled={enviando}
            ultimaIdempotencyKey={ultimaIdempotencyKey}
          />
        </section>

        {error && (
          <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Estado de la transacción
          </h2>
          <StatusTimeline transaccion={transaccion} />
        </section>
      </div>
    </div>
  );
}
