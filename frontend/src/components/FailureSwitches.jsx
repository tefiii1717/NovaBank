function Switch({ etiqueta, descripcion, checked, onChange, disabled, colorActivo }) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition
        ${checked ? colorActivo : "border-slate-200 bg-white"}
        ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <input
        type="checkbox"
        className="mt-1 h-4 w-4"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="block text-sm font-semibold text-slate-800">{etiqueta}</span>
        <span className="block text-xs text-slate-500">{descripcion}</span>
      </span>
    </label>
  );
}

export default function FailureSwitches({ flags, onChange, disabled }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      <Switch
        etiqueta="CP-02 · Fondos insuficientes"
        descripcion="Fuerza un monto artificialmente alto para el rechazo inmediato."
        checked={flags.forzarFondosInsuficientes}
        onChange={(v) => onChange({ ...flags, forzarFondosInsuficientes: v })}
        disabled={disabled}
        colorActivo="border-rose-300 bg-rose-50"
      />
      <Switch
        etiqueta="CP-03 · Forzar fraude"
        descripcion="El servicio de Riesgo rechaza la operación (RiesgoRechazado)."
        checked={flags.forzarFraude}
        onChange={(v) => onChange({ ...flags, forzarFraude: v })}
        disabled={disabled}
        colorActivo="border-rose-300 bg-rose-50"
      />
      <Switch
        etiqueta="CP-04 · Forzar timeout de red"
        descripcion="La Pasarela Interbancaria simula caída de red externa."
        checked={flags.forzarTimeout}
        onChange={(v) => onChange({ ...flags, forzarTimeout: v })}
        disabled={disabled}
        colorActivo="border-rose-300 bg-rose-50"
      />
    </div>
  );
}
