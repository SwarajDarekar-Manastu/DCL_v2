<script lang="ts">
	// One telemetry file with several channels without a unit, as a reviewer who never saw the pipeline needs it:
	// what is wrong (banner), the file itself with the channel boxed, one row per channel with a unit picker,
	// a preview of the converted values, and one "Apply all" (and resume, when the file is halted).
	import { untrack } from 'svelte';
	import { ApiError, dryRun, previewRule, resolveCase, type CaseDetail, type DryRunResponse, type RulePreview } from '$lib/api_endpoint';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import FlagGuide from './FlagGuide.svelte';
	import { caseRuleScope, type ScopeChoice } from './resolution';
	import {
		AMBIENT_OPTIONS,
		candidateChoices,
		channelRows,
		choiceFor,
		proposedRows,
		columnOf,
		displayRange,
		findChoice,
		fmt,
		sampleValues,
		setUnit,
		sourceTable,
		sparkPath,
		UNIT_GROUPS,
		type Ambient
	} from './channel_map';

	interface Props {
		detail: CaseDetail;
		onChanged: () => void;
		onDetails: () => void;
		/** the case view is busy with another action */
		locked?: boolean;
	}

	let { detail, onChanged, onDetails, locked = false }: Props = $props();
	let rows = $derived(channelRows(detail));
	let picked = $state<Record<string, string>>({});
	let ambient = $state<Ambient>('SEA_LEVEL');
	let selected = $state<string | null>(null);
	let previews = $state<Record<string, DryRunResponse | string>>({});
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let scopeChoice = $state<ScopeChoice>('file');
	let pattern = $state('');
	let reach = $state<RulePreview | null>(null);
	let where = $derived(detail.locations[0] ?? null);

	// Start each channel on its suggestion; a new case starts clean. When a rule proposes units, show what they
	// convert to at once, so the reviewer sees the numbers before applying.
	let caseKey = $derived(detail.summary.case_key);
	let applyLabel = $derived(detail.document_status === 'HALTED' ? 'Apply all and resume' : 'Apply all');
	$effect(() => {
		void caseKey;
		picked = Object.fromEntries(rows.map((r) => [r.flag.flag_id, choiceFor(r)?.id ?? '']));
		previews = {};
		selected = rows[0]?.flag.flag_id ?? null;
		error = '';
		notice = '';
		scopeChoice = 'file';
		pattern = '';
		reach = null;
		if (untrack(() => proposed.length)) queueMicrotask(() => void previewAll());
	});

	let proposed = $derived(proposedRows(rows));
	let unchanged = $derived(proposed.length > 0 && proposed.every((r) => picked[r.flag.flag_id] === (choiceFor(r)?.id ?? '')));
	let proposalChecked = $derived(proposed.length > 0 && proposed.every((r) => typeof previews[r.flag.flag_id] === 'object'));
	let proposalOutOfRange = $derived(proposed.filter((r) => inSanity(r.flag.flag_id) === false).map((r) => r.channel));
	let proposalNote = $derived(proposed.find((r) => r.rationale)?.rationale ?? '');

	// How many files the chosen reach would free, before anything is saved.
	let scope = $derived.by(() => {
		try {
			return where ? caseRuleScope(scopeChoice, where, pattern) : null;
		} catch {
			return null;
		}
	});
	$effect(() => {
		const chosen = scope;
		if (!chosen) {
			reach = null;
			return;
		}
		const timer = setTimeout(() => previewRule({ rule_type: 'channel_proposal', scope: chosen }).then((p) => (reach = p)).catch(() => (reach = null)), 250);
		return () => clearTimeout(timer);
	});
	let scopeMissing = $derived(scopeChoice !== 'file' && !scope);

	let active = $derived(rows.find((r) => r.flag.flag_id === selected) ?? rows[0] ?? null);
	let table = $derived(active ? sourceTable(active.evidence) : { columns: [], rows: [] });
	let boxed = $derived(active ? columnOf(table, active) : -1);
	let hard = $derived(rows.some((r) => r.flag.severity === 'HARD'));

	function resolutionOf(flagId: string) {
		const row = rows.find((r) => r.flag.flag_id === flagId);
		const choice = row ? findChoice(row, picked[flagId] ?? '') : null;
		return row && choice ? setUnit(row, choice, ambient) : null;
	}
	let chosen = $derived(rows.filter((r) => resolutionOf(r.flag.flag_id)));
	let anyGauge = $derived(chosen.some((r) => resolutionOf(r.flag.flag_id)?.gauge_or_abs === 'gauge'));
	let previewed = $derived(chosen.length > 0 && chosen.every((r) => typeof previews[r.flag.flag_id] === 'object'));

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	function pick(flagId: string, id: string) {
		picked[flagId] = id;
		delete previews[flagId];
	}

	async function previewAll() {
		busy = true;
		error = '';
		for (const r of chosen) {
			try {
				previews[r.flag.flag_id] = await dryRun({ case_key: caseKey, resolution: { flag_id: r.flag.flag_id, resolution: resolutionOf(r.flag.flag_id)! } });
			} catch (e) {
				previews[r.flag.flag_id] = describe(e);
			}
		}
		busy = false;
	}

	async function applyRows(which: typeof rows) {
		busy = true;
		error = '';
		notice = '';
		try {
			const response = await resolveCase(caseKey, {
				resolutions: which.map((r) => ({ flag_id: r.flag.flag_id, resolution: resolutionOf(r.flag.flag_id)! })),
				rule_scope: scope,
				comment: 'channel map'
			});
			const proposed = response.proposed_files;
			notice = `Approved the units of ${which.length} channel${which.length === 1 ? '' : 's'}${response.resumed_doc_ids.length ? '. This file is resuming' : ''}${proposed ? `. ${proposed} other file${proposed === 1 ? '' : 's'} now show${proposed === 1 ? 's' : ''} these units as a proposal, waiting for a person` : ''}.`;
			onChanged();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}
	const applyAll = () => applyRows(chosen);
	const applyProposed = () => applyRows(proposed);

	function restoreProposal() {
		for (const r of proposed) {
			picked[r.flag.flag_id] = choiceFor(r)?.id ?? '';
			delete previews[r.flag.flag_id];
		}
		void previewAll();
	}

	const converted = (flagId: string) => {
		const p = previews[flagId];
		if (!p || typeof p === 'string') return p ?? '';
		const c = p.channels?.[0];
		return c ? displayRange(c.stat_min, c.stat_max, c.unit_si) : 'no converted values';
	};
	const inSanity = (flagId: string) => {
		const p = previews[flagId];
		return p && typeof p === 'object' ? (p.channels?.[0]?.within_sanity ?? null) : null;
	};
</script>

<section class="grid gap-4" aria-label="Channel map">
	<div class="bg-warn-bg border-warn-border rounded-lg border px-4 py-3" role="status">
		<p class="m-0 flex items-center gap-1.5 font-medium">
			This file has {rows.length} columns with no unit. Pick the unit for each so processing can continue.
			<FlagGuide topic="UNIT_AMBIGUITY" />
		</p>
		<p class="text-muted-foreground m-0 mt-1 text-[13px]">
			Each column is a measurement <abbr title="A channel is one column of a test-data file: one sensor recorded over time.">channel</abbr>. Until every channel has a unit the file is
			<abbr title="Halted: the pipeline stopped before indexing this file, so its numbers cannot be searched or used in answers yet.">halted</abbr>{hard
				? ''
				: ' only in part'}{hard ? ' (' : ''}{#if hard}<abbr title="HARD flags stop the file until they are resolved; SOFT flags only warn and the file stays usable.">HARD</abbr>){/if}.
		</p>
	</div>

	{#if proposed.length}
		<div class="border-info-border bg-info-bg grid gap-2 rounded-lg border px-4 py-3" role="region" aria-label="Proposed by a rule">
			<p class="m-0 font-medium">A rule proposes the units of {proposed.length} of {rows.length} columns.</p>
			<p class="text-muted-foreground m-0 text-[13px]">
				{proposalNote ? `${proposalNote[0].toUpperCase()}${proposalNote.slice(1)}.` : ''} Nothing is approved yet: check the converted numbers below, then apply it or skip the file.
			</p>
			{#if proposalOutOfRange.length}
				<Notice tone="warning">These look wrong once converted: {proposalOutOfRange.join(', ')}. Choose another unit, or skip the file.</Notice>
			{/if}
			<div class="flex flex-wrap items-center gap-2">
				{#if unchanged}
					<Button disabled={busy || locked || !proposalChecked || proposalOutOfRange.length > 0} onclick={applyProposed}>
						<CheckIcon />Apply proposed rule{proposed.length < rows.length ? ` (${proposed.length} of ${rows.length} columns)` : ''}
					</Button>
					{#if !proposalChecked}<span class="text-muted-foreground text-xs">Checking the numbers…</span>{/if}
				{:else}
					<Button variant="outline" disabled={busy || locked} onclick={restoreProposal}>Back to the proposed units</Button>
					<span class="text-muted-foreground text-xs">You changed a proposed unit, so apply with "{applyLabel}" below.</span>
				{/if}
			</div>
		</div>
	{/if}

	{#if table.columns.length}
		<section aria-label="The file as it was read" class="grid gap-1.5">
			<h3 class="eyebrow m-0">The file as it was read{active ? `: column ${active.channel} is outlined` : ''}</h3>
			{#if active?.evidence.header_lines.length}
				<pre class="code-block m-0 max-h-24 text-[11px]">{active.evidence.header_lines.filter((l) => l.trim()).slice(0, 4).join('\n')}</pre>
			{/if}
			<div class="overflow-x-auto rounded-md border">
				<table class="w-full border-collapse font-mono text-[11px]" aria-label="Source rows">
					<thead>
						<tr class="bg-muted/60">
							{#each table.columns as col, c (c)}
								<th class="relative px-2 py-1 text-left font-medium {c === boxed ? 'outline-info outline-2 -outline-offset-2' : ''}" data-boxed={c === boxed ? 'true' : undefined}>{col}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each table.rows.slice(0, 12) as r, i (i)}
							<tr class="border-t">
								{#each r as v, c (c)}<td class="px-2 py-0.5 text-right whitespace-nowrap {c === boxed ? 'bg-info-bg' : ''}">{fmt(v)}</td>{/each}
							</tr>
						{:else}
							<tr><td colspan={table.columns.length} class="text-muted-foreground px-2 py-1 font-sans">Only the header is available for this file.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	<div class="overflow-x-auto rounded-md border">
		<table class="w-full text-sm" aria-label="Channels">
			<thead>
				<tr class="bg-muted/60 text-muted-foreground text-left text-xs">
					<th class="px-2.5 py-1.5 font-medium">Channel</th><th class="px-2.5 py-1.5 font-medium">First values</th><th class="px-2.5 py-1.5 font-medium">Over the run</th
					><th class="px-2.5 py-1.5 font-medium">Unit</th><th class="px-2.5 py-1.5 font-medium">Converted (preview)</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as r (r.flag.flag_id)}
					{@const path = sparkPath(r.evidence.series as [number, number | null][])}
					<tr
						class="cursor-pointer border-t align-top {selected === r.flag.flag_id ? 'bg-muted/50' : ''}"
						aria-selected={selected === r.flag.flag_id}
						onclick={() => (selected = r.flag.flag_id)}
					>
						<td class="px-2.5 py-1.5 font-mono font-medium">{r.channel}{#if r.flag.severity === 'HARD'}<span class="text-hard text-[11px]">{' HARD'}</span>{/if}</td>
						<td class="px-2.5 py-1.5 font-mono text-xs">{sampleValues(r).join(', ') || '—'}</td>
						<td class="px-2.5 py-1.5">
							{#if path}<svg width="120" height="28" viewBox="0 0 120 28" role="img" aria-label="Values of {r.channel} over the run"><path d={path} fill="none" stroke="currentColor" stroke-width="1.2" class="text-info" /></svg>{/if}
							<span class="text-muted-foreground block font-mono text-[11px]">{fmt(r.evidence.stats.min)} … {fmt(r.evidence.stats.max)}</span>
						</td>
						<td class="px-2.5 py-1.5">
							<select
								class="field h-8 w-52"
								aria-label="Unit of {r.channel}"
								value={picked[r.flag.flag_id] ?? ''}
								onclick={(e) => e.stopPropagation()}
								onchange={(e) => pick(r.flag.flag_id, (e.currentTarget as HTMLSelectElement).value)}
							>
								<option value="">choose a unit…</option>
								{#if candidateChoices(r.evidence).length}
									<optgroup label="Suggested by the pipeline">
										{#each candidateChoices(r.evidence) as c (c.id)}<option value={c.id}>{c.label}</option>{/each}
									</optgroup>
								{/if}
								{#each UNIT_GROUPS as g (g.quantity)}
									<optgroup label={g.label}>{#each g.choices as c (c.id)}<option value={c.id}>{c.label}</option>{/each}</optgroup>
								{/each}
							</select>
							{#if r.byRule}<span class="text-info block text-[11px]">proposed by a rule</span>{:else if r.suggestion}<span class="text-muted-foreground block text-[11px]">suggested · confidence {Math.round((r.confidence ?? 0) * 100)}%</span>{/if}
							{#if r.evidence.scaling_equation}<span class="text-muted-foreground block font-mono text-[11px]" title={r.evidence.scaling_source ?? ''}>.cfg: {r.evidence.scaling_equation}</span>{/if}
						</td>
						<td class="px-2.5 py-1.5 text-xs {inSanity(r.flag.flag_id) === false ? 'text-hard' : inSanity(r.flag.flag_id) ? 'text-ok' : ''}">{converted(r.flag.flag_id)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if anyGauge}
		<label class="field-label grid w-fit gap-1"
			>Gauge readings are relative to
			<select class="field w-56" bind:value={ambient} onchange={() => (previews = {})}>
				{#each AMBIENT_OPTIONS as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
			</select>
		</label>
	{/if}

	<fieldset class="m-0 grid gap-1.5 rounded-md border px-4 py-3">
		<legend class="px-1 text-[13px] font-medium">Also propose to</legend>
		<div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
			<label class="flex items-center gap-1.5"><input type="radio" bind:group={scopeChoice} value="file" /> no other file</label>
			<label class="flex items-center gap-1.5"><input type="radio" bind:group={scopeChoice} value="folder" disabled={!where?.folder_id} /> the other files in this folder</label>
			<label class="flex items-center gap-1.5"
				><input type="radio" bind:group={scopeChoice} value="folder_pattern" disabled={!where?.folder_id} /> files in this folder named
				<input class="field h-7 w-28 font-mono" bind:value={pattern} placeholder="T*.dat" disabled={scopeChoice !== 'folder_pattern'} aria-label="File name pattern" /></label
			>
		</div>
		{#if scopeChoice === 'file'}
			<p class="text-muted-foreground m-0 text-xs">Only this file is decided. Other files keep waiting for their own check.</p>
		{:else if reach}
			<p class="m-0 text-xs" aria-live="polite">
				Saved as a proposal rule for the folder: it reaches {reach.matched_documents} file{reach.matched_documents === 1 ? '' : 's'}, {reach.waiting_documents} waiting (this one included). They show
				these units and files that arrive later do too, but none is approved until a person applies it.
			</p>
		{:else if scopeMissing}
			<p class="text-muted-foreground m-0 text-xs">Type a file name pattern such as T*.dat.</p>
		{/if}
	</fieldset>

	<footer class="flex flex-wrap items-center gap-2">
		<Button variant="outline" disabled={busy || !chosen.length} onclick={previewAll}>Preview all</Button>
		<Button disabled={busy || locked || !previewed || scopeMissing} onclick={applyAll}><CheckIcon />{applyLabel}</Button>
		<span class="text-muted-foreground text-xs">
			{chosen.length} of {rows.length} channels have a unit{!previewed && chosen.length ? '; preview first to see the converted values' : ''}.
		</span>
		<button type="button" class="text-link ml-auto cursor-pointer border-0 bg-transparent p-0 text-xs" onclick={onDetails}>Show per-flag details</button>
	</footer>
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}
</section>
