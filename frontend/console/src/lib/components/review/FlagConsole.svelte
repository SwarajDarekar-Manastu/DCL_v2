<script lang="ts">
	import type { DryRunResponse, FlagView, Resolution, ResolutionAction } from '$lib/api_endpoint';
	import DryRunPanel from './DryRunPanel.svelte';
	import EvidencePane from './EvidencePane.svelte';
	import ResolutionForm from './ResolutionForm.svelte';
	import { ACTION_LABEL, allowedActions, missing, needsPreview, startDraft } from './resolution';

	interface Props {
		flag: FlagView;
		draft: Resolution | null;
		preview: { result: DryRunResponse | null; error: string; current: boolean; busy: boolean };
		onPreview: () => void;
	}

	let { flag, draft = $bindable(), preview, onPreview }: Props = $props();
	let actions = $derived(allowedActions(flag));
	let open = $derived(['OPEN', 'IN_PROGRESS', 'REOPENED'].includes(flag.status));
	let gap = $derived(draft ? missing(draft) : null);

	function choose(action: ResolutionAction | '') {
		draft = action ? startDraft(action, flag) : null;
	}
	function pickUnit(unit: string, gaugeOrAbs: string) {
		const next = draft?.action === 'set_unit' ? draft : startDraft('set_unit', flag);
		if (next.action !== 'set_unit') return;
		next.unit = unit;
		next.gauge_or_abs = gaugeOrAbs as typeof next.gauge_or_abs;
		next.expression = null;
		draft = next;
	}
	const where = (a: FlagView['anchor']) =>
		[a.page && `page ${a.page}`, a.sheet && `sheet ${a.sheet}`, a.channel && `channel ${a.channel}`, a.column && `column ${a.column}`, a.line && `line ${a.line}`]
			.filter(Boolean)
			.join(' · ');
</script>

<article class="flag" aria-label="{flag.flag_type} flag">
	<header>
		<span class="sev sev-{flag.severity}">⚠ {flag.flag_type} ({flag.severity})</span>
		<span class="where">{where(flag.anchor)}</span>
		<span class="status">{flag.status}</span>
	</header>
	{#if flag.severity === 'HARD' && open}
		<p class="halt">Pipeline halted for this document until this flag is resolved.</p>
	{/if}

	<div class="body">
		<EvidencePane evidence={flag.evidence ?? null} suggestion={flag.suggested_resolution ?? null} onPickUnit={open ? pickUnit : undefined} />

		<div class="console">
			{#if open}
				<label
					>Resolution
					<select value={draft?.action ?? ''} onchange={(e) => choose((e.currentTarget as HTMLSelectElement).value as ResolutionAction | '')}>
						<option value="">leave open</option>
						{#each actions as action (action)}<option value={action}>{ACTION_LABEL[action]}</option>{/each}
					</select>
				</label>
				{#if draft}
					<ResolutionForm bind:draft />
					{#if gap}<p class="gap">Missing: {gap}</p>{/if}
					{#if needsPreview(draft.action)}
						<button type="button" disabled={!!gap || preview.busy} onclick={onPreview}>Preview conversion</button>
						{#if preview.error}<p class="gap" role="alert">{preview.error}</p>{/if}
						{#if preview.result && preview.current}
							<DryRunPanel result={preview.result} />
						{:else if preview.result}
							<p class="gap">The draft changed since the preview; preview again before applying.</p>
						{/if}
					{/if}
				{/if}
			{:else}
				<p>Resolved {flag.resolved_at ? `on ${flag.resolved_at.slice(0, 10)}` : ''} {flag.resolved_by ? `by ${flag.resolved_by}` : ''}</p>
				{#if flag.resolution}<pre>{JSON.stringify(flag.resolution, null, 2)}</pre>{/if}
			{/if}
		</div>
	</div>
</article>

<style>
	.flag {
		border: 1px solid var(--border);
		border-radius: 0.45rem;
		background: var(--surface);
		padding: 0.7rem;
		display: grid;
		gap: 0.5rem;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		align-items: baseline;
		font-size: 0.85rem;
	}
	.sev {
		font-weight: 700;
	}
	.sev-HARD {
		color: var(--hard);
	}
	.status {
		margin-left: auto;
		font-size: 0.75rem;
		opacity: 0.75;
	}
	.halt {
		margin: 0;
		font-size: 0.8rem;
	}
	.body {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
		gap: 1rem;
	}
	@media (max-width: 1100px) {
		.body {
			grid-template-columns: 1fr;
		}
	}
	.console {
		display: grid;
		gap: 0.5rem;
		align-content: start;
	}
	label {
		display: grid;
		gap: 0.15rem;
		font-size: 0.82rem;
	}
	select {
		font: inherit;
		padding: 0.25rem;
		background: var(--bg);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	.gap {
		margin: 0;
		font-size: 0.8rem;
		color: var(--warn);
	}
	button {
		justify-self: start;
		font: inherit;
		font-size: 0.82rem;
		padding: 0.3rem 0.7rem;
		cursor: pointer;
	}
	pre {
		font-size: 0.78rem;
		white-space: pre-wrap;
	}
</style>
