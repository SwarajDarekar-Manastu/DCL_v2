<script lang="ts">
	import type { DryRunResponse, FlagView, Resolution, ResolutionAction } from '$lib/api_endpoint';
	import OctagonPauseIcon from '@lucide/svelte/icons/octagon-pause';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import SeverityBadge from '$lib/components/shell/SeverityBadge.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import FlagGuide from './FlagGuide.svelte';
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

<article
	class={['panel overflow-hidden', flag.severity === 'HARD' && open && 'border-hard-border']}
	aria-label="{flag.flag_type} flag"
>
	<header class="panel-header bg-muted/40 flex-wrap justify-start gap-2">
		<SeverityBadge severity={flag.severity} />
		<h3 class="m-0 font-mono text-[13px] font-semibold">{flag.flag_type} <span class="sr-only">({flag.severity})</span></h3>
		<FlagGuide flagType={flag.flag_type} />
		{#if where(flag.anchor)}<span class="text-muted-foreground text-xs">{where(flag.anchor)}</span>{/if}
		<ToneBadge tone={open ? 'outline' : 'ok'} class="ml-auto">{flag.status}</ToneBadge>
	</header>
	{#if flag.severity === 'HARD' && open}
		<p class="bg-hard-bg text-hard border-hard-border m-0 flex items-center gap-2 border-b px-4 py-1.5 text-xs font-medium">
			<OctagonPauseIcon class="size-3.5 shrink-0" aria-hidden="true" /> Pipeline halted for this document until this flag is resolved.
		</p>
	{/if}

	<div class="grid gap-5 p-4 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
		<EvidencePane evidence={flag.evidence ?? null} suggestion={flag.suggested_resolution ?? null} onPickUnit={open ? pickUnit : undefined} />

		<div class="grid content-start gap-3 2xl:border-l 2xl:pl-5">
			{#if open}
				<label class="grid gap-1"
					><span class="field-label">Resolution</span>
					<select
						class="field"
						value={draft?.action ?? ''}
						onchange={(e) => choose((e.currentTarget as HTMLSelectElement).value as ResolutionAction | '')}
					>
						<option value="">leave open</option>
						{#each actions as action (action)}<option value={action}>{ACTION_LABEL[action]}</option>{/each}
					</select>
				</label>
				{#if draft}
					<ResolutionForm bind:draft />
					{#if gap}<Notice tone="warning">Missing: {gap}</Notice>{/if}
					{#if needsPreview(draft.action)}
						<Button variant="outline" size="sm" class="justify-self-start" disabled={!!gap || preview.busy} onclick={onPreview}>Preview conversion</Button>
						{#if preview.error}<Notice tone="error">{preview.error}</Notice>{/if}
						{#if preview.result && preview.current}
							<DryRunPanel result={preview.result} />
						{:else if preview.result}
							<Notice tone="warning">The draft changed since the preview; preview again before applying.</Notice>
						{/if}
					{/if}
				{/if}
			{:else}
				<p class="text-muted-foreground m-0 text-[13px]">
					Resolved {flag.resolved_at ? `on ${flag.resolved_at.slice(0, 10)}` : ''} {flag.resolved_by ? `by ${flag.resolved_by}` : ''}
				</p>
				{#if flag.resolution}<pre class="code-block m-0">{JSON.stringify(flag.resolution, null, 2)}</pre>{/if}
			{/if}
		</div>
	</div>
</article>
