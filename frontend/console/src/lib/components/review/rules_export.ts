// Rules export (file 08 §4.2 RulesPage "export YAML") in the file format of S1's backend/review/rules.py
// (`RulesFile`: version, rules[status, rule_type, scope, precedence, body, created_by]); `load_yaml` reads it back
// into config/rules/. Only active operator rules are exported, as `status: operator`. Strings are written as
// double-quoted scalars, so no value can change type on the way back.

import type { RuleView } from '$lib/api_endpoint';

export const EXPORT_VERSION = 1;

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

const PLAIN_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
const key = (k: string) => (PLAIN_KEY.test(k) ? k : JSON.stringify(k));
const scalar = (v: string | number | boolean | null) => (typeof v === 'string' ? JSON.stringify(v) : v === null ? 'null' : String(v));
const isScalar = (v: Json): v is string | number | boolean | null => v === null || typeof v !== 'object';

function lines(value: Json, indent: string): string[] {
	if (Array.isArray(value)) {
		if (value.length === 0) return [`${indent}[]`];
		return value.flatMap((item) => {
			if (isScalar(item)) return [`${indent}- ${scalar(item)}`];
			const inner = lines(item, indent + '  ');
			return [`${indent}- ${inner[0].trimStart()}`, ...inner.slice(1)];
		});
	}
	if (isScalar(value)) return [`${indent}${scalar(value)}`];
	const entries = Object.entries(value);
	if (entries.length === 0) return [`${indent}{}`];
	return entries.flatMap(([k, v]) => {
		if (isScalar(v)) return [`${indent}${key(k)}: ${scalar(v)}`];
		if ((Array.isArray(v) && v.length === 0) || (!Array.isArray(v) && Object.keys(v).length === 0))
			return [`${indent}${key(k)}: ${Array.isArray(v) ? '[]' : '{}'}`];
		return [`${indent}${key(k)}:`, ...lines(v, indent + '  ')];
	});
}

export function toYaml(value: Json): string {
	return lines(value, '').join('\n') + '\n';
}

const withoutNulls = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== undefined));

/** The RulesFile of the active operator rules. */
export function rulesFile(rules: RuleView[]): Json {
	return {
		version: EXPORT_VERSION,
		rules: rules
			.filter((r) => r.origin === 'operator' && r.active)
			.map((r) =>
				withoutNulls({
					status: 'operator',
					rule_type: r.rule_type,
					scope: withoutNulls(r.scope as Record<string, unknown>),
					precedence: r.precedence,
					body: r.body,
					created_by: r.created_by
				}) as Json
			)
	};
}

export function rulesYaml(rules: RuleView[], exportedAt: string): string {
	return `# DCL operator rules exported from the Console at ${exportedAt}; load with backend/review/rules.py load_yaml\n` + toYaml(rulesFile(rules));
}
