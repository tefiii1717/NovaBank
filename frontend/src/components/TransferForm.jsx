import { useState } from "react";
import FailureSwitches from "./FailureSwitches.jsx";

const MONTO_FONDOS_INSUFICIENTES = 999999999;

export default function TransferForm({ onSubmit, disabled, ultimaIdempotencyKey }) {
  const [origen, setOrigen] = useState("CTA-001");
  const [destino, setDestino] = useState("CTA-002");
  const [monto, setMonto] = useState(100);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [flags, setFlags] = useState({
    forzarFondosInsuficientes: false,
    forzarFraude: false,
    forzarTimeout: false,
  });

  function manejarSubmit(e) {
    e.preventDefault();
    onSubmit({
      origen,
      destino,
      monto: flags.forzarFondosInsuficientes ? MONTO_FONDOS_INSUFICIENTES : Number(monto),
      idempotencyKey: idempotencyKey.trim() || null,
      forzarFraude: flags.forzarFraude,
      forzarTimeout: flags.forzarTimeout,
    });
  }

  return (
    <form onSubmit={manejarSubmit} className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Cuenta origen</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2"
            value={origen}
            onChange={(e) => setOrigen(e.target.value)}
            disabled={disabled}
            required
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Cuenta destino</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2"
            value={destino}
            onChange={(e) => setDestino(e.target.value)}
            disabled={disabled}
            required
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Monto</span>
          <input
            type="number"
            min="0.01"
            step="0.01"
            className="w-full rounded-md border border-slate-300 px-3 py-2 disabled:bg-slate-100"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
            disabled={disabled || flags.forzarFondosInsuficientes}
            required
          />
        </label>
      </div>

      <FailureSwitches flags={flags} onChange={setFlags} disabled={disabled} />

      <div className="flex items-end gap-2">
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium text-slate-700">
            Idempotency key (opcional — vacío = se genera un UUID nuevo)
          </span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
            placeholder="p.ej. cp05-mi-prueba"
            value={idempotencyKey}
            onChange={(e) => setIdempotencyKey(e.target.value)}
            disabled={disabled}
          />
        </label>
        {ultimaIdempotencyKey && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setIdempotencyKey(ultimaIdempotencyKey)}
            className="rounded-md border border-slate-300 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            title="CP-05: reenviar con el mismo idempotency_key que la última transferencia"
          >
            Reusar último ID (CP-05)
          </button>
        )}
      </div>

      <button
        type="submit"
        disabled={disabled}
        className="w-full rounded-lg bg-slate-900 px-4 py-2.5 font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {disabled ? "Procesando…" : "Enviar transferencia"}
      </button>
    </form>
  );
}
