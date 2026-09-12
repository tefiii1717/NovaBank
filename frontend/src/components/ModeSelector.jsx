import { MODOS } from "../constants.js";

export default function ModeSelector({ modo, onCambiar, disabled }) {
  const opciones = [
    { valor: MODOS.COREOGRAFIA, etiqueta: "Coreografiada (Redis)", puerto: "8100" },
    { valor: MODOS.ORQUESTACION, etiqueta: "Orquestada (Prefect)", puerto: "8200" },
  ];

  return (
    <div className="flex gap-2">
      {opciones.map((op) => (
        <button
          key={op.valor}
          type="button"
          disabled={disabled}
          onClick={() => onCambiar(op.valor)}
          className={`flex-1 rounded-lg border px-4 py-2 text-sm font-medium transition
            ${modo === op.valor
              ? "border-slate-900 bg-slate-900 text-white"
              : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}
            disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {op.etiqueta}
          <span className="block text-xs font-normal opacity-70">:{op.puerto}</span>
        </button>
      ))}
    </div>
  );
}
