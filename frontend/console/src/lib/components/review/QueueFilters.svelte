<script lang="ts">
	import type { CaseFilters } from '$lib/api_endpoint';

	interface Props {
		filters: CaseFilters;
		onChange: (filters: CaseFilters) => void;
	}

	let { filters, onChange }: Props = $props();

	const FLAG_TYPES = [
		'UNIT_AMBIGUITY',
		'SCHEMA_UNKNOWN',
		'LOW_CONFIDENCE_EXTRACTION',
		'PARSE_FAILURE',
		'UNSUPPORTED_FORMAT',
		'CONFLICT',
		'SENSITIVE_CONTENT',
		'HELD_LARGE_FILE',
		'CLOUD_RESTRICTED'
	] as const;
	const ROUTES = ['A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'G'] as const;
	const STATUSES = ['OPEN', 'IN_PROGRESS', 'REOPENED', 'RESOLVED', 'REJECTED_FILE'] as const;

	function set<K extends keyof CaseFilters>(key: K, value: CaseFilters[K] | '') {
		const next = { ...filters, [key]: value === '' ? undefined : value };
		onChange(next);
	}
	const secondary = $derived(
		[filters.route, filters.status, filters.root_name, filters.test_plan_id, filters.assignee, filters.has_suggestion].filter(
			(v) => v !== undefined && v !== ''
		).length
	);
	const FIELD = 'grid min-w-0 gap-1';
	const text = (e: Event) => (e.currentTarget as HTMLInputElement | HTMLSelectElement).value;
</script>

<form class="grid gap-2.5" aria-label="Queue filters" onsubmit={(e) => e.preventDefault()}>
	<div class="grid grid-cols-[5.5rem_minmax(0,1fr)_5.5rem] gap-2">
		<label class={FIELD}
			><span class="field-label">Severity</span>
			<select class="field" value={filters.severity ?? ''} onchange={(e) => set('severity', text(e) as CaseFilters['severity'])}>
				<option value="">any</option>
				<option value="HARD">HARD</option>
				<option value="SOFT">SOFT</option>
			</select>
		</label>
		<label class={FIELD}
			><span class="field-label">Flag type</span>
			<select class="field" value={filters.flag_type ?? ''} onchange={(e) => set('flag_type', text(e) as CaseFilters['flag_type'])}>
				<option value="">any</option>
				{#each FLAG_TYPES as t (t)}<option value={t}>{t}</option>{/each}
			</select>
		</label>
		<label class={FIELD}
			><span class="field-label">Sort</span>
			<select class="field" value={filters.sort ?? 'impact'} onchange={(e) => set('sort', text(e) as CaseFilters['sort'])}>
				<option value="impact">impact</option>
				<option value="age">age</option>
				<option value="severity">severity</option>
			</select>
		</label>
	</div>
	<details class="group" open={secondary > 0}>
		<summary class="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs font-medium [&::-webkit-details-marker]:hidden">
			<span class="inline-block transition-transform group-open:rotate-90" aria-hidden="true">›</span>
			More filters{#if secondary}<span class="bg-foreground text-background num ml-1 rounded-full px-1.5 text-[10px] leading-4">{secondary}</span>{/if}
		</summary>
		<div class="mt-2.5 grid grid-cols-2 gap-2">
			<label class={FIELD}
				><span class="field-label">Route</span>
				<select class="field" value={filters.route ?? ''} onchange={(e) => set('route', text(e) as CaseFilters['route'])}>
					<option value="">any</option>
					{#each ROUTES as r (r)}<option value={r}>{r}</option>{/each}
				</select>
			</label>
			<label class={FIELD}
				><span class="field-label">Status</span>
				<select class="field" value={filters.status ?? ''} onchange={(e) => set('status', text(e) as CaseFilters['status'])}>
					<option value="">open</option>
					{#each STATUSES as s (s)}<option value={s}>{s}</option>{/each}
				</select>
			</label>
			<label class={FIELD}><span class="field-label">Root</span> <input class="field" value={filters.root_name ?? ''} onchange={(e) => set('root_name', text(e))} /></label>
			<label class={FIELD}
				><span class="field-label">Test plan</span> <input class="field" value={filters.test_plan_id ?? ''} onchange={(e) => set('test_plan_id', text(e))} /></label
			>
			<label class={FIELD}><span class="field-label">Assignee</span> <input class="field" value={filters.assignee ?? ''} onchange={(e) => set('assignee', text(e))} /></label>
			<label class="flex items-center gap-2 self-end pb-1.5 text-[13px]"
				><input
					type="checkbox"
					checked={filters.has_suggestion === true}
					onchange={(e) => set('has_suggestion', (e.currentTarget as HTMLInputElement).checked ? true : undefined)}
				/> Has suggestion</label
			>
		</div>
	</details>
</form>
