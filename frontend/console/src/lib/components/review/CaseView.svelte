<script lang="ts">
	import {
		ApiError,
		assignCase,
		dryRun,
		rejectCase,
		resolveCase,
		undoCase,
		type CaseDetail,
		type DryRunResponse,
		type Resolution,
		type RuleDraft
	} from '$lib/api_endpoint';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import CaseHeader from './CaseHeader.svelte';
	import ChannelMapView from './ChannelMapView.svelte';
	import FlagConsole from './FlagConsole.svelte';
	import { isChannelMapCase } from './channel_map';
	import { canBecomeRule, missing, needsPreview, ruleFor, type ScopeChoice } from './resolution';

	interface Props {
		detail: CaseDetail;
		/** the signed-in reviewer, as the API names assignees */
		me: string;
		/** reload the case and the queue after an action */
		onChanged: () => void;
	}

	let { detail, me, onChanged }: Props = $props();

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

	// A different case starts clean.
	let caseKey = $derived(detail.summary.case_key);
	$effect(() => {
		void caseKey;
		drafts = {};
		previews = {};
		scope = 'file';
		pattern = '';
		error = '';
		notice = '';
		details = false;
	});

	let where = $derived(detail.locations[0] ?? null);
	let chosen = $derived(
		Object.entries(drafts).filter((entry): entry is [string, Resolution] => entry[1] !== null)
	);
	let ruleCandidates = $derived(chosen.filter(([, r]) => canBecomeRule(r.action)));
	let ruleFlagId = $derived(ruleCandidates.length === 1 ? ruleCandidates[0][0] : null);
	let rule = $derived.by((): { draft: RuleDraft | null; error: string } => {
		if (scope === 'file' || !ruleFlagId) return { draft: null, error: '' };
		if (!where) return { draft: null, error: 'This case has no OneDrive location to scope a rule to.' };
		try {
			return { draft: ruleFor(drafts[ruleFlagId]!, scope, where, pattern), error: '' };
		} catch (e) {
			return { draft: null, error: (e as Error).message };
		}
	});

	const signatureOf = (flagId: string) =>
		JSON.stringify({ draft: drafts[flagId], rule: flagId === ruleFlagId ? rule.draft : null });

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
				resolution: { flag_id: flagId, resolution },
				rule: flagId === ruleFlagId ? rule.draft : null
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
		if (scope !== 'file' && ruleCandidates.length > 1) return 'A folder scope applies to one resolution at a time.';
		if (rule.error) return rule.error;
		for (const [flagId, r] of chosen) {
			if (needsPreview(r.action) && !(previewState(flagId).current && !previews[flagId]?.error && previews[flagId]?.result)) {
				return 'Preview the conversion before applying.';
			}
		}
		return '';
	});

	let affected = $derived(
		ruleFlagId && previews[ruleFlagId]?.result ? previews[ruleFlagId]!.result!.affected_documents : null
	);

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

	const apply = () =>
		run(async () => {
			const response = await resolveCase(caseKey, {
				resolutions: chosen.map(([flag_id, resolution]) => ({ flag_id, resolution })),
				rule: rule.draft
			});
			const resumed = response.resumed_doc_ids.length;
			return `Resolved. ${resumed} document${resumed === 1 ? '' : 's'} resuming${response.rule ? ' under the new rule' : ''}.`;
		});
	const reject = (action: 'skip' | 'mark_junk') =>
		run(async () => {
			await rejectCase(caseKey, { action });
			return action === 'skip' ? 'File skipped.' : 'File marked as junk.';
		});
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

<section class="grid gap-4" aria-label="Case">
	<CaseHeader {detail} {me} {busy} onAssign={assign} onUndo={undo} />

	{#if isChannelMapCase(detail) && !details}
		<ChannelMapView {detail} {onChanged} onDetails={() => (details = true)} />
	{:else}
	{#if isChannelMapCase(detail)}
		<button type="button" class="text-link w-fit cursor-pointer border-0 bg-transparent p-0 text-xs" onclick={() => (details = false)}>Back to the channel map</button>
	{/if}
	<div class="grid gap-3">
		{#each detail.flags as flag (flag.flag_id)}
			<FlagConsole {flag} bind:draft={drafts[flag.flag_id]} preview={previewState(flag.flag_id)} onPreview={() => preview(flag.flag_id)} />
		{/each}
	</div>

	<footer class="bg-background/95 sticky bottom-0 z-10 -mx-5 grid gap-2 border-t px-5 py-3 backdrop-blur">
		{#if ruleCandidates.length}
			<fieldset class="m-0 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-0 p-0 text-[13px]">
				<legend class="field-label float-left mr-2">Apply to</legend>
				<label class="flex items-center gap-1.5"><input type="radio" bind:group={scope} value="file" /> this file</label>
				<label class="flex items-center gap-1.5"><input type="radio" bind:group={scope} value="folder" disabled={!where?.folder_id} /> this folder</label>
				<label class="flex items-center gap-1.5"
					><input type="radio" bind:group={scope} value="folder_pattern" disabled={!where?.folder_id} /> this folder, files matching
					<input class="field h-7 w-28 font-mono" bind:value={pattern} placeholder="T*.dat" disabled={scope !== 'folder_pattern'} /></label
				>
			</fieldset>
			{#if scope !== 'file'}<Notice tone="info">Saved as an operator rule; matching halted files resume too.</Notice>{/if}
		{/if}
		<div class="flex flex-wrap items-center gap-2">
			<Button disabled={busy || !!blocker} onclick={apply}>
				<CheckIcon />Apply & resume{affected !== null ? ` (${affected} file${affected === 1 ? '' : 's'})` : ''}
			</Button>
			<Button variant="outline" disabled={busy} onclick={() => reject('mark_junk')}>Mark junk</Button>
			<Button variant="outline" disabled={busy} onclick={() => reject('skip')}>Skip file</Button>
			{#if blocker}<p class="text-muted-foreground m-0 ml-1 text-xs">{blocker}</p>{/if}
		</div>
		{#if error}<Notice tone="error">{error}</Notice>{/if}
		{#if notice}<Notice tone="success">{notice}</Notice>{/if}
	</footer>
	{/if}
</section>
