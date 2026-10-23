// The channel-map view of a telemetry case (user request 2026-10-23): one row per channel of the halted file, the
// file itself with the active column boxed, and one "apply all". Data: S1's unit_telemetry evidence (columns,
// column_index, sample_rows, time_column, series; backend/dispatcher/contract.py UnitTelemetryEvidence).

import type { CaseDetail, Evidence, FlagView, Resolution } from '$lib/api_endpoint';

export type TelemetryEvidence = Extract<Evidence, { kind: 'unit_telemetry' }>;
type SetUnit = Extract<Resolution, { action: 'set_unit' }>;

const OPEN = new Set(['OPEN', 'IN_PROGRESS', 'REOPENED']);

export interface ChannelRow {
	flag: FlagView;
	channel: string;
	evidence: TelemetryEvidence;
	/** the suggestion's set_unit, when the pipeline or a rule proposed one */
	suggestion: SetUnit | null;
	confidence: number | null;
	/** the suggestion comes from a saved rule, not from the file's own hints */
	byRule: boolean;
	/** why it is proposed, in the words of whoever produced it */
	rationale: string | null;
}

const telemetry = (f: FlagView): TelemetryEvidence | null => (f.evidence?.kind === 'unit_telemetry' ? f.evidence : null);

/** The open telemetry unit flags of the case, one per channel, in the file's column order. */
export function channelRows(detail: Pick<CaseDetail, 'flags'>): ChannelRow[] {
	const rows = detail.flags
		.filter((f) => f.flag_type === 'UNIT_AMBIGUITY' && OPEN.has(f.status) && telemetry(f))
		.map((flag) => {
			const evidence = telemetry(flag)!;
			const suggested = flag.suggested_resolution?.resolution;
			return {
				flag,
				channel: evidence.channel,
				evidence,
				suggestion: suggested?.action === 'set_unit' ? suggested : null,
				confidence: suggested?.action === 'set_unit' ? (flag.suggested_resolution?.confidence ?? null) : null,
				byRule: suggested?.action === 'set_unit' && flag.suggested_resolution?.proposed_by === 'rule',
				rationale: suggested?.action === 'set_unit' ? (flag.suggested_resolution?.rationale ?? null) : null
			};
		});
	const order = (r: ChannelRow) => r.evidence.column_index ?? Number.MAX_SAFE_INTEGER;
	return rows.sort((a, b) => order(a) - order(b) || a.channel.localeCompare(b.channel));
}

/** The channel map replaces the per-flag consoles when a file has two or more channels without a unit. */
export const isChannelMapCase = (detail: Pick<CaseDetail, 'flags'>) => channelRows(detail).length >= 2;

export interface UnitChoice {
	id: string;
	label: string;
	unit: string;
	quantity: string;
	gauge_or_abs: 'gauge' | 'absolute' | 'n/a' | 'unknown';
}

/** Units a reviewer picks from, grouped by quantity; values are pint units (S1 converts with pint). */
export const UNIT_GROUPS: { quantity: string; label: string; choices: UnitChoice[] }[] = [
	{
		quantity: 'pressure',
		label: 'Pressure',
		choices: [
			{ id: 'bar_g', label: 'bar (gauge)', unit: 'bar', quantity: 'pressure', gauge_or_abs: 'gauge' },
			{ id: 'bar_a', label: 'bar (absolute)', unit: 'bar', quantity: 'pressure', gauge_or_abs: 'absolute' },
			{ id: 'psig', label: 'psi (gauge)', unit: 'psi', quantity: 'pressure', gauge_or_abs: 'gauge' },
			{ id: 'psia', label: 'psi (absolute)', unit: 'psi', quantity: 'pressure', gauge_or_abs: 'absolute' },
			{ id: 'kpa_g', label: 'kPa (gauge)', unit: 'kPa', quantity: 'pressure', gauge_or_abs: 'gauge' },
			{ id: 'kpa_a', label: 'kPa (absolute)', unit: 'kPa', quantity: 'pressure', gauge_or_abs: 'absolute' },
			{ id: 'mbar_a', label: 'mbar (absolute)', unit: 'mbar', quantity: 'pressure', gauge_or_abs: 'absolute' }
		]
	},
	{
		quantity: 'temperature',
		label: 'Temperature',
		choices: [
			{ id: 'degc', label: '°C', unit: 'degC', quantity: 'temperature', gauge_or_abs: 'n/a' },
			{ id: 'k', label: 'K', unit: 'K', quantity: 'temperature', gauge_or_abs: 'n/a' },
			{ id: 'degf', label: '°F', unit: 'degF', quantity: 'temperature', gauge_or_abs: 'n/a' }
		]
	},
	{
		quantity: 'flow',
		label: 'Flow, force',
		choices: [
			{ id: 'g_s', label: 'g/s', unit: 'g/s', quantity: 'mass_flow_rate', gauge_or_abs: 'n/a' },
			{ id: 'kg_s', label: 'kg/s', unit: 'kg/s', quantity: 'mass_flow_rate', gauge_or_abs: 'n/a' },
			{ id: 'n', label: 'N', unit: 'N', quantity: 'force', gauge_or_abs: 'n/a' }
		]
	},
	{
		quantity: 'electrical',
		label: 'Raw signal',
		choices: [
			{ id: 'v', label: 'V (raw voltage)', unit: 'V', quantity: 'voltage', gauge_or_abs: 'n/a' },
			{ id: 'mv', label: 'mV (raw voltage)', unit: 'mV', quantity: 'voltage', gauge_or_abs: 'n/a' },
			{ id: 'ma', label: 'mA (current loop)', unit: 'mA', quantity: 'current', gauge_or_abs: 'n/a' }
		]
	}
];

const ALL = UNIT_GROUPS.flatMap((g) => g.choices);

/** The pipeline's own candidates (most likely first) as choices, ahead of the fixed list. */
export function candidateChoices(evidence: TelemetryEvidence): UnitChoice[] {
	return evidence.candidate_units.map((c, i) => ({
		id: `candidate_${i}`,
		label: `${c.unit}${c.gauge_or_abs === 'gauge' ? ' (gauge)' : c.gauge_or_abs === 'absolute' ? ' (absolute)' : ''} · ${Math.round(c.score * 100)}%`,
		unit: c.unit,
		quantity: evidence.quantity_guess ?? 'pressure',
		gauge_or_abs: c.gauge_or_abs
	}));
}

/** The choice matching a suggestion (or a candidate), so the picker can start preselected. */
export function choiceFor(row: ChannelRow): UnitChoice | null {
	const s = row.suggestion;
	if (!s) return null;
	return (
		[...candidateChoices(row.evidence), ...ALL].find((c) => c.unit === s.unit && c.gauge_or_abs === s.gauge_or_abs) ?? {
			id: 'suggested',
			label: `${s.unit} (${s.gauge_or_abs})`,
			unit: s.unit,
			quantity: s.quantity,
			gauge_or_abs: s.gauge_or_abs === 'unknown' ? 'unknown' : s.gauge_or_abs
		}
	);
}

export const findChoice = (row: ChannelRow, id: string) => [...candidateChoices(row.evidence), ...ALL].find((c) => c.id === id) ?? null;

export type Ambient = 'VACUUM_CHAMBER' | 'SEA_LEVEL' | 'AMBIENT_RECORDED' | 'UNKNOWN';

/** What a gauge reading is relative to, in the words the Console uses wherever it asks. */
export const AMBIENT_OPTIONS: { value: Ambient; label: string }[] = [
	{ value: 'SEA_LEVEL', label: 'sea-level air (1.013 bar)' },
	{ value: 'AMBIENT_RECORDED', label: 'the ambient recorded in the run' },
	{ value: 'VACUUM_CHAMBER', label: 'a vacuum chamber' },
	{ value: 'UNKNOWN', label: 'not known' }
];

/** The set_unit resolution for a channel and a chosen unit; gauge units carry the shared ambient reference. */
export function setUnit(row: ChannelRow, choice: UnitChoice, ambient: Ambient | null): SetUnit {
	const proposed = row.suggestion;
	// A rule's chosen name stays only while the unit is the proposed one: the name often carries the unit.
	const name = proposed?.canonical_name && proposed.unit === choice.unit && proposed.gauge_or_abs === choice.gauge_or_abs ? proposed.canonical_name : null;
	return {
		action: 'set_unit',
		channel: row.channel,
		unit: choice.unit,
		quantity: choice.quantity,
		gauge_or_abs: choice.gauge_or_abs,
		ambient_condition: choice.gauge_or_abs === 'gauge' ? ambient : null,
		ambient_pressure_bar_abs: null,
		expression: null,
		canonical_name: name
	};
}

/** The columns a rule proposes a unit for, and whether the pickers still hold exactly its units. */
export function proposedRows(rows: ChannelRow[]): ChannelRow[] {
	return rows.filter((r) => r.byRule);
}

export interface SourceTable {
	columns: string[];
	rows: (string | number | null)[][];
}

/** The file as parsed: columns and the first rows; without them, the column line of the header. */
export function sourceTable(evidence: TelemetryEvidence): SourceTable {
	if (evidence.columns.length) return { columns: evidence.columns, rows: evidence.sample_rows };
	const header = [...evidence.header_lines].reverse().find((l) => l.split('\t').length > 2) ?? '';
	return { columns: header ? header.split('\t').map((c) => c.trim()) : [], rows: [] };
}

/** The column of a channel in the source table (the evidence's column_index, else by name). */
export function columnOf(table: SourceTable, row: ChannelRow): number {
	if (row.evidence.column_index !== null && row.evidence.column_index !== undefined && table.columns === row.evidence.columns)
		return row.evidence.column_index;
	return table.columns.indexOf(row.channel);
}

/** First values of the channel, formatted short. */
export function sampleValues(row: ChannelRow, n = 4): string[] {
	const i = row.evidence.column_index;
	if (i === null || i === undefined) return [];
	return row.evidence.sample_rows.slice(0, n).map((r) => fmt(r[i]));
}

export const fmt = (v: string | number | null | undefined): string =>
	v === null || v === undefined ? '—' : typeof v === 'number' ? String(Number(v.toPrecision(5))) : v;

/** An SVG path through the series, scaled into width × height (gaps break the line). */
export function sparkPath(series: [number, number | null][], width = 120, height = 28): string {
	const points = series.filter((p): p is [number, number] => p[1] !== null && Number.isFinite(p[1]));
	if (points.length < 2) return '';
	const [t0, t1] = [points[0][0], points[points.length - 1][0]];
	const values = points.map((p) => p[1]);
	const [lo, hi] = [Math.min(...values), Math.max(...values)];
	const x = (t: number) => ((t - t0) / (t1 - t0 || 1)) * width;
	const y = (v: number) => height - 1 - ((v - lo) / (hi - lo || 1)) * (height - 2);
	let path = '';
	let pen = false;
	for (const [t, v] of series) {
		if (v === null || !Number.isFinite(v)) {
			pen = false;
			continue;
		}
		path += `${pen ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
		pen = true;
	}
	return path;
}

/**
 * The dry run's unit_si is pint's name for the canonical unit (backend/common/units.py CANONICAL_UNITS) or, for a
 * dimension without one, its base-unit expansion. Reviewers read symbols, and temperatures in °C.
 */
const SYMBOLS: Record<string, string> = {
	bar: 'bar',
	newton: 'N',
	'gram / second': 'g/s',
	watt: 'W',
	ampere: 'A',
	volt: 'V',
	'kilogram * meter ** 2 / ampere / second ** 3': 'V'
};

export function unitSymbol(unit: string): string {
	if (unit in SYMBOLS) return SYMBOLS[unit];
	return unit
		.replace(/ \*\* 2/g, '²')
		.replace(/ \*\* 3/g, '³')
		.replace(/ \* /g, '·')
		.replace(/ \/ /g, '/');
}

/** "286 … 317 bar"; kelvin is shown in °C. */
export function displayRange(min: number | null | undefined, max: number | null | undefined, unit: string): string {
	const kelvin = unit === 'kelvin';
	const shift = (v: number | null | undefined) => (v === null || v === undefined ? v : kelvin ? v - 273.15 : v);
	return `${fmt(shift(min))} … ${fmt(shift(max))} ${kelvin ? '°C' : unitSymbol(unit)}`;
}
