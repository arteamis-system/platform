import { createHash } from 'node:crypto';

import type { FindingType } from './types.js';

/**
 * A stable dedup key for a finding (TRD §8.1):
 *   fp = hash(type + endpoint + normalized_signature + environment)
 *
 * The signature is normalized so cosmetic differences (ids, timestamps, uuids,
 * hex, trailing digits in paths) don't spawn a new issue for the same defect.
 */
export function normalizeSignature(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, '<uuid>')
    .replace(/0x[0-9a-f]+/g, '<hex>')
    .replace(/\b\d{4}-\d{2}-\d{2}t[\d:.]+z?\b/g, '<ts>')
    .replace(/\/\d+(?=\/|$)/g, '/<id>')
    .replace(/\b\d+\b/g, '<n>')
    .replace(/\s+/g, ' ')
    .trim();
}

export function fingerprint(input: {
  type: FindingType;
  endpoint: string;
  signature: string;
  environment: string;
}): string {
  const canonical = [
    input.type,
    input.endpoint.trim().toLowerCase(),
    normalizeSignature(input.signature),
    input.environment,
  ].join(' ');
  return createHash('sha256').update(canonical).digest('hex').slice(0, 16);
}
