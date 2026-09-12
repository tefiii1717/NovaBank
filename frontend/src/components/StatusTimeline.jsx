import { ESTADOS, EVENTOS_LABEL } from "../constants.js";

function formatearHora(timestamp) {
  try {
    return new Date(timestamp).toLocaleTimeString();
  } catch {
    return timestamp;
  }
}

export default function StatusTimeline({ transaccion }) {
  if (!transaccion) {
    return (
      <p className="text-sm text-slate-500">
        Todavía no has enviado ninguna transferencia en este modo.
      </p>
    );
  }

  const infoEstado = ESTADOS[transaccion.estado] || ESTADOS.EN_EJECUCION;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-slate-500">{transaccion.idempotency_key}</p>
          <p className="text-sm text-slate-600">
            {transaccion.origen} → {transaccion.destino} · ${transaccion.monto}
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-sm font-semibold ${infoEstado.color}`}>
          {infoEstado.etiqueta}
        </span>
      </div>

      <ol className="space-y-2">
        {transaccion.historial.map((paso, i) => {
          const pasoInfo = ESTADOS[paso.estado_paso] || ESTADOS.EN_EJECUCION;
          return (
            <li key={i} className="flex items-start gap-3 rounded-lg border border-slate-200 p-3">
              <span className={`mt-0.5 h-2.5 w-2.5 flex-shrink-0 rounded-full ${pasoInfo.color.split(" ")[0]}`} />
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">
                    {EVENTOS_LABEL[paso.tipo] || paso.tipo}
                  </span>
                  <span className="text-xs text-slate-400">{formatearHora(paso.timestamp)}</span>
                </div>
                <p className="text-xs text-slate-500">
                  {paso.origen_servicio}
                  {paso.data && paso.data.motivo ? ` — motivo: ${paso.data.motivo}` : ""}
                  {paso.data && paso.data.accion ? ` — acción: ${paso.data.accion}` : ""}
                </p>
              </div>
            </li>
          );
        })}
        {transaccion.historial.length === 0 && (
          <li className="text-sm text-slate-400">Esperando el primer evento…</li>
        )}
      </ol>
    </div>
  );
}
