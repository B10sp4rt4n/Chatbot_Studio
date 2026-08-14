# Chatbot Studio Event Contract v0.1

## Propósito

Este contrato convierte cada interacción con IA en una trayectoria temporal reconstruible. El registro no se limita al prompt y la respuesta: conserva identidad, inspección, decisión, awareness, paso por el proveedor, registro Recordia y custodia HotVault.

## Dos niveles de representación

1. **Evento atómico:** hecho inmutable con `occurred_at`, `recorded_at`, secuencia y hash.
2. **Paquete de interacción:** proyección legible construida a partir de todos los eventos de una interacción.

El paquete puede reconstruirse cuantas veces sea necesario. Los eventos originales no se actualizan.

## Orden mínimo

```text
INTERACTION_RECEIVED
→ IDENTITY_VERIFIED
→ CONTENT_INSPECTED
→ POLICY_DECIDED
→ AWARENESS_PRESENTED (obligatorio ante intervención)
→ USER_ACKNOWLEDGED (cuando corresponda)
→ PROVIDER_REQUESTED (sólo si está autorizado)
→ PROVIDER_RESPONDED
→ INTERACTION_RECORDED
→ EVIDENCE_VAULTED (opcional y posterior)
```

Las decisiones `REVIEW` pueden producir `REVIEW_APPROVED` o `REVIEW_REJECTED`. Sólo una revisión aprobada puede continuar al proveedor.

## Tiempo

- Todas las fechas deben incluir zona horaria.
- El servidor normaliza las fechas a UTC durante la canonicalización.
- `occurred_at` representa cuándo ocurrió el hecho.
- `recorded_at` representa cuándo Recordia incorporó el hecho a la cadena.
- `recorded_at` nunca puede ser anterior a `occurred_at`.
- Los eventos de una interacción conservan orden temporal no decreciente.
- La estampa participa en `record_hash`; alterarla invalida el evento.

La vista consolidada expone, cuando existen:

- `occurred_at`
- `identity_verified_at`
- `inspected_at`
- `decided_at`
- `awareness_presented_at`
- `user_acknowledged_at`
- `review_approved_at` o `review_rejected_at`
- `sent_to_provider_at`
- `response_received_at`
- `recorded_at`
- `vaulted_at`

## Integridad Recordia

`payload_hash` es SHA-256 sobre el payload canonicalizado. `record_hash` es SHA-256 sobre el evento completo, salvo el propio `record_hash`, e incluye:

- identidad y tenant;
- tipo de evento;
- interacción y sesión;
- ambas estampas temporales;
- secuencia;
- `previous_hash`;
- payload y `payload_hash`;
- versión de esquema y canonicalización.

La canonicalización `CS-CANONICAL-JSON-v1` usa UTF-8, claves ordenadas, separadores compactos, fechas UTC con precisión de milisegundos y rechaza valores numéricos no finitos.

## HotVault

La preservación no agrega `vaulted_at` al registro ya sellado. Genera `EVIDENCE_VAULTED` con:

```json
{
  "parent_event_id": "evt_recorded_...",
  "parent_record_hash": "<sha256>",
  "vault_reference": "hotvault://...",
  "evidence_hash": "<sha256>",
  "retention_class": "security-evidence"
}
```

Esto conserva la inmutabilidad y crea una cadena de custodia explícita.

## Aislamiento

- La secuencia y la cadena son independientes por tenant.
- Toda consulta requiere `tenant_id`.
- Una referencia a un evento de otro tenant se rechaza, aunque el `event_id` exista.
- Una referencia a otra interacción del mismo tenant también se rechaza.
- El contenido puede cifrarse en una capa posterior sin cambiar el contrato del evento.

La API v0.1 es una superficie de desarrollo: el `tenant_id` todavía es suministrado por el cliente y no representa autenticación. No debe publicarse como servicio multitenant hasta derivar el tenant de una identidad autenticada.

## Estados de usuario

El contrato acepta `NORMAL`, `GUIDED`, `APPROVAL_REQUIRED` y `SUSPENDED` dentro de los payloads de identidad o decisión. La política que provoca la transición pertenece a AUP; Recordia conserva el hecho y su explicación.

## Compatibilidad

El esquema está en `schemas/interaction-event-v0.1.schema.json`. Cualquier cambio incompatible exige una versión nueva. Los eventos v0.1 existentes no se reescriben.
