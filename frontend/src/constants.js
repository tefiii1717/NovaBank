// Debe coincidir exactamente con docs/CONTRATO_EVENTOS.md — así el frontend
// pinta el mismo resultado sin importar si la saga la resolvió el modo
// orquestado (Sofía/Prefect) o el coreografiado (Yuly/Redis).

export const ESTADOS = {
  EN_EJECUCION: { etiqueta: "En ejecución", color: "bg-amber-100 text-amber-800 border-amber-300" },
  CONFIRMADO: { etiqueta: "Confirmado", color: "bg-emerald-100 text-emerald-800 border-emerald-300" },
  RECHAZADO_FONDOS: { etiqueta: "Rechazado — fondos insuficientes", color: "bg-rose-100 text-rose-800 border-rose-300" },
  RECHAZADO_RIESGO: { etiqueta: "Rechazado — riesgo/fraude", color: "bg-rose-100 text-rose-800 border-rose-300" },
  RECHAZADO_RED: { etiqueta: "Rechazado — caída de red", color: "bg-rose-100 text-rose-800 border-rose-300" },
  COMPENSADO: { etiqueta: "Compensado", color: "bg-sky-100 text-sky-800 border-sky-300" },
};

export const ESTADOS_TERMINALES = new Set([
  "CONFIRMADO",
  "RECHAZADO_FONDOS",
  "RECHAZADO_RIESGO",
  "RECHAZADO_RED",
]);

// RECHAZADO_RIESGO y RECHAZADO_RED siempre van seguidos de CompensacionEjecutada
// (la reversa ocurre DESPUÉS del rechazo, nunca antes). Si el polling se detuviera
// apenas se ve el estado final, el paso "Compensado" nunca llegaría a pintarse.
export const ESTADOS_CON_COMPENSACION_ESPERADA = new Set([
  "RECHAZADO_RIESGO",
  "RECHAZADO_RED",
]);

export const EVENTOS_LABEL = {
  TransferenciaSolicitada: "Transferencia solicitada",
  SaldoDebitado: "Saldo debitado (Cuentas)",
  RiesgoAprobado: "Riesgo aprobado",
  RiesgoRechazado: "Riesgo rechazado (fraude)",
  LiquidacionConfirmada: "Liquidación confirmada (Pasarela)",
  TransferenciaFallida: "Transferencia fallida",
  CompensacionEjecutada: "Compensación ejecutada",
};

export const MODOS = {
  COREOGRAFIA: "coreografia",
  ORQUESTACION: "orquestacion",
};
