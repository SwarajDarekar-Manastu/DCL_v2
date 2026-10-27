<script lang="ts">
	import {
		ApiError,
		assignCase,
		dryRun,
		resolveCase,
		undoCase,
		type CaseDetail,
		type DryRunResponse,
		type Resolution
	} from '$lib/api_endpoint';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import CaseHeader from './CaseHeader.svelte';
	import ChannelMapView from './ChannelMapView.svelte';
	import FlagConsole from './FlagConsole.svelte';
	import RuleFromDecision from './RuleFromDecision.svelte';
	import { isChannelMapCase } from './channel_map';
	import { tick, untrack } from 'svelte';
	import { decisionText, subjectText } from './decisions';
	import { loadDrafts, saveDrafts } from './drafts';
	import { canBecomeRule, caseRuleScope, missing, needsPreview, takesFileOut, type ScopeChoice } from './resolution';
	import { offersFor, type RuleOffer } from './rule_from_decision';

	interface Props {
		detail: CaseDetail;
		/** the signed-in reviewer, as the API names assignees */
		me: string;
		/** reload the case and the queue after an action */
		onChanged: () => void;
	}

	let { detail, me, onChanged }: Props = $props();
	const OPEN = ['OPEN', 'IN_PROGRESS', 'REOPENED'];

	interface Preview {
		result: DryRunResponse | null;
		error: string;
		signature: string;
		busy: boolean;
	}

	let drafts = $state<Record<string, Resolution | null>>({});
	let previews = $state<Record<string, Preview>>({});
	let scope = $state<ScopeChoice>('file');
	let pattern = $state('');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let details = $state(false);
	// A choice that takes the whole file out of search waits for a second click.
	let confirming = $state(false);
	// "Make a rule from this decision": the rules that would repeat what was just applied.
	let offers = $state<RuleOffer[]>([]);

	// A different case starts with its own saved drafts (kept across a trip to the viewer or a reload).
	let caseKey = $derived(detail.summary.case_key);
	let openFlags = $derived(detail.flags.filter((f) => OPEN.includes(f.status)));
	let decidedFlags = $derived(detail.flags.filter((f) => !OPEN.includes(f.status)));
	let caseEl = $state<HTMLElement | null>(null);
	$effect(() => {
		void caseKey;
		drafts = loadDrafts(caseKey, untrack(() => openFlags.map((f) => f.flag_id)));
		previews = {};
		scope = 'file';
		pattern = '';
		error = '';
		notice = '';
		details = false;
		confirming = false;
		offers = [];
		// Focus lands on the first open question's Resolution, so the keyboard can go on from the queue.
		void tick().then(() => (caseEl?.querySelector<HTMLElement>('select[data-resolution]') ?? caseEl)?.focus());
	});
	$effect(() => saveDrafts(caseKey, drafts));

	let where = $derived(detail.locations[0] ?? null);
	let chosen = $derived(
		Object.entries(drafts).filter((entry): entry is [string, Resolution] => entry[1] !== null)
	);
	let ruleCandidates = $derived(chosen.filter(([, r]) => canBecomeRule(r.action)));
	let wholeFile = $derived(
		chosen.find(([flagId, r]) => {
			const flag = detail.flags.find((f) => f.flag_id === flagId);
			return !!flag && takesFileOut(flag, r.action);
		})?.[1].action ?? null
	);
	// "Also propose to": the scope of the proposal rule saved with this approval; null is this file only.
	let ruleScope = $derived.by(() => {
		try {
			return where && ruleCandidates.length ? caseRuleScope(scope, where, pattern) : null;
		} catch {
			return null;
		}
	});
	let scopeError = $derived(
		ruleCandidates.length && scope !== 'file' && !ruleScope
			? where
				? 'Type a file name pattern such as T*.dat.'
				: 'This case has no OneDrive location to scope a proposal to.'
			: ''
	);

	const signatureOf = (flagId: string) => JSON.stringify({ draft: drafts[flagId] });

	function previewState(flagId: string) {
		const p = previews[flagId];
		return {
			result: p?.result ?? null,
			error: p?.error ?? '',
			busy: p?.busy ?? false,
			current: !!p && p.signature === signatureOf(flagId)
		};
	}

	async function preview(flagId: string) {
		const resolution = drafts[flagId];
		if (!resolution) return;
		const signature = signatureOf(flagId);
		previews[flagId] = { result: null, error: '', signature, busy: true };
		try {
			const result = await dryRun({
				case_key: caseKey,
				resolution: { flag_id: flagId, resolution }
			});
			previews[flagId] = { result, error: '', signature, busy: false };
		} catch (e) {
			previews[flagId] = { result: null, error: describe(e), signature, busy: false };
		}
	}

	let blocker = $derived.by((): string => {
		if (!chosen.length) return 'Choose a resolution for at least one flag.';
		for (const [, r] of chosen) {
			const gap = missing(r);
			if (gap) return `Missing: ${gap}.`;
		}
		if (scopeError) return scopeError;
		for (const [flagId, r] of chosen) {
			if (needsPreview(r.action) && !(previewState(flagId).current && !previews[flagId]?.error && previews[flagId]?.result)) {
				return 'Preview the conversion before applying.';
			}
		}
		return '';
	});

	function describe(e: unknown): string {
		return e instanceof ApiError ? (e.status === 501 ? 'The review backend is not connected yet.' : e.detail) : String(e);
	}

	async function run(action: () => Promise<string>) {
		busy = true;
		error = '';
		notice = '';
		try {
			notice = await action();
			onChanged();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	function apply() {
		if (wholeFile && !confirming) {
			confirming = true;
			return;
		}
		confirming = false;
		void run(async () => {
			const repeatable = offersFor(detail.flags, chosen, where?.file_name ?? '');
			const response = await resolveCase(caseKey, {
				resolutions: chosen.map(([flag_id, resolution]) => ({ flag_id, resolution })),
				rule_scope: ruleScope
			});
			offers = repeatable;
			saveDrafts(caseKey, {});
			const proposed = response.proposed_files;
			return `Resolved${response.resumed_doc_ids.length ? '. This file is resuming' : ''}${proposed ? `. ${proposed} other file${proposed === 1 ? '' : 's'} now show${proposed === 1 ? 's' : ''} these units as a proposal` : ''}.`;
		});
	}

	const assign = (assignee: string | null) =>
		run(async () => {
			await assignCase(caseKey, assignee);
			return assignee ? `Assigned to ${assignee}.` : 'Unassigned.';
		});
	const undo = () =>
		run(async () => {
			const response = await undoCase(caseKey);
			return `Reopened ${response.reopened_flag_ids.length} flag${response.reopened_flag_ids.length === 1 ? '' : 's'}.`;
		});
</script>

<section class="grid gap-4 outline-none" aria-label="Case" tabindex="-1" bind:this={caseEl}>
	<CaseHeader {detail} {me} {busy} onAssign={assign} onUndo={undo} />

	{#if isChannelMapCase(detail) && !details}
		<ChannelMapView {detail} {onChanged} onDetails={() => (details = true)} locked={busy} />
	{:else}
	{#if isChannelMapCase(detail)}
		<button type="button" class="text-link w-fit cursor-pointer border-0 bg-transparent p-0 text-xs" onclick={() => (details = false)}>Back to the channel map</button>
	{/if}
	<div class="grid gap-3">
		{#each openFlags as flag (flag.flag_id)}
			<FlagConsole {flag} bind:draft={drafts[flag.flag_id]} preview={previewState(flag.flag_id)} onPreview={() => preview(flag.flag_id)} />
		{/each}
	</div>
	{#if decidedFlags.length}
		<details class="rounded-md border" open={!openFlags.length}>
			<summary class="text-muted-foreground hover:text-foreground cursor-pointer px-3 py-2 text-[13px] font-medium">Decided earlier ({decidedFlags.length})</summary>
			<ul class="m-0 grid list-none gap-0 border-t p-0 text-[13px]" aria-label="Decided earlier">
				{#each decidedFlags as flag (flag.flag_id)}
					<li class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b px-3 py-1.5 last:border-b-0">
						<span class="min-w-48 font-medium">{subjectText(flag)}</span>
						<span>{decisionText(flag)}</span>
						<span class="text-muted-foreground ml-auto text-xs"
							>{flag.resolved_by ?? ''}{flag.resolved_at ? ` · ${flag.resolved_at.slice(0, 10)}` : ''}</span
						>
					</li>
				{/each}
			</ul>
		</details>
	{/if}

	{#if offers.length}
		<RuleFromDecision {offers} {where} onSaved={onChanged} onDismiss={() => (offers = [])} />
	{/if}

	<footer class="bg-background/95 sticky bottom-0 z-10 -mx-5 grid gap-2 border-t px-5 py-3 backdrop-blur">
		{#if ruleCandidates.length}
			<fieldset class="m-0 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-0 p-0 text-[13px]">
				<legend class="field-label float-left mr-2">Also propose to</legend>
				<label class="flex items-center gap-1.5"><input type="radio" bind:group={scope} value="file" /> no other file</label>
				<label class="flex items-center gap-1.5"><input type="radio" bind:group={scope} value="folder" disabled={!where?.folder_id} /> the other files in this folder</label>
				<label class="flex items-center gap-1.5"
					><input type="radio" bind:group={scope} value="folder_pattern" disabled={!where?.folder_id} /> files in this folder named
					<input class="field h-7 w-28 font-mono" bind:value={pattern} placeholder="T*.dat" disabled={scope !== 'folder_pattern'} /></label
				>
			</fieldset>
			{#if scope !== 'file'}<Notice tone="info">Saved as a proposal rule: the other waiting files show these units, and a person still checks and applies each one.</Notice>{/if}
		{/if}
		<div class="flex flex-wrap items-center gap-2">
			<Button disabled={busy || !!blocker} onclick={apply}>
				<CheckIcon />{detail.document_status === 'HALTED' ? 'Apply & resume' : 'Apply'}
			</Button>
			{#if blocker}<p class="text-muted-foreground m-0 ml-1 text-xs">{blocker}</p>{/if}
		</div>
		{#if confirming && wholeFile}
			<Notice tone="warning"
				>{wholeFile === 'mark_junk' ? 'Junk' : 'Skip'} the whole file <strong>{where?.file_name ?? 'of this case'}</strong>? It leaves search{wholeFile ===
				'mark_junk'
					? ' and is not processed again'
					: ''}. Undo brings it back.</Notice
			>
			<div class="flex flex-wrap items-center gap-2">
				<Button variant="destructive" disabled={busy} onclick={apply}>Yes, {wholeFile === 'mark_junk' ? 'junk' : 'skip'} the whole file</Button>
				<Button variant="outline" disabled={busy} onclick={() => (confirming = false)}>Cancel</Button>
			</div>
		{/if}
		{#if error}<Notice tone="error">{error}</Notice>{/if}
		{#if notice}<Notice tone="success">{notice}</Notice>{/if}
	</footer>
	{/if}
</section>
