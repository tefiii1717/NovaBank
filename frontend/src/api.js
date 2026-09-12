import { MODOS } from "./constants.js";

const BASE_URLS = {
  [MODOS.COREOGRAFIA]: import.meta.env.VITE_GATEWAY_COREOGRAFIA_URL || "http://localhost:8100",
  [MODOS.ORQUESTACION]: import.meta.env.VITE_GATEWAY_ORQUESTADA_URL || "http://localhost:8200",
};

export function urlBase(modo) {
  return BASE_URLS[modo];
}

export async function crearTransferencia(modo, { origen, destino, monto, idempotencyKey, forzarFraude, forzarTimeout }) {
  const respuesta = await fetch(`${urlBase(modo)}/transferencia`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      origen,
      destino,
      monto,
      idempotency_key: idempotencyKey || null,
      flags_fallo: {
        forzar_fraude: forzarFraude,
        forzar_timeout: forzarTimeout,
      },
    }),
  });
  if (!respuesta.ok) {
    const detalle = await respuesta.text();
    throw new Error(`Error ${respuesta.status} al crear la transferencia: ${detalle}`);
  }
  return respuesta.json();
}

export async function obtenerEstado(modo, idempotencyKey) {
  const respuesta = await fetch(`${urlBase(modo)}/transferencia/${idempotencyKey}/estado`);
  if (!respuesta.ok) {
    const detalle = await respuesta.text();
    throw new Error(`Error ${respuesta.status} al consultar el estado: ${detalle}`);
  }
  return respuesta.json();
}
