<script lang="ts">
	// The units a person approved for a file, with who and when, and an edit form: choose another unit or name,
	// see the converted numbers, write why, save. The file is rebuilt with the new units and the audit log keeps
	// the signed-in reviewer, the reason and the before and after (POST /review/cases/{key}/edit).
	import { ApiError, dryRun, editCase, type CaseDetail, type DryRunResponse } from '$lib/api_endpoint';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import ReopenButton from './ReopenButton.svelte';
	import { AMBIENT_OPTIONS, UNIT_GROUPS, displayRange, type Ambient } from './channel_map';
	import { editedResolution, editProblem, isChanged, isGaugeAfter, startEdit, toSave, unitDecisions, type Edit } from './decisions';

	interface Props {
		detail: CaseDetail;
		/** reload the file after a change */
		onChanged: () => void;
		/** the file was reopened: go and decide it again */
		onReopened: () => void;
	}

	let { detail, onChanged, onReopened }: Props = $props();
	let decisions = $derived(unitDecisions(detail));
	let caseKey = $derived(detail.summary.case_key);

	let editing = $state(false);
	let edits = $state<Record<string, Edit>>({});
	let ambient = $state<Ambient>('SEA_LEVEL');
	let reason = $state('');
	let previews = $state<Record<string, { key: string; result: DryRunResponse | string }>>({});
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '');
	let changed = $derived(toSave(decisions, edits));
	let unchecked = $derived(decisions.filter((d) => d.appliedBy));
	let confirming = $derived(changed.length > 0 && !decisions.some((d) => isChanged(d, edits[d.flag.flag_id])));
	let problem = $derived(editProblem(decisions, edits, reason));
	const keyOf = (id: string) => {
		const d = decisions.find((x) => x.flag.flag_id === id);
		return d && edits[id] ? JSON.stringify(editedResolution(d, edits[id], ambient)) : '';
	};
	let previewed = $derived(changed.length > 0 && changed.every((d) => previews[d.flag.flag_id]?.key === keyOf(d.flag.flag_id) && typeof previews[d.flag.flag_id]?.result === 'object'));

	function start() {
		edits = Object.fromEntries(decisions.map((d) => [d.flag.flag_id, startEdit(d)]));
		ambient = decisions.find((d) => d.resolution.ambient_condition)?.resolution.ambient_condition ?? 'SEA_LEVEL';
		reason = '';
		previews = {};
		error = '';
		notice = '';
		editing = true;
	}

	async function previewChanges() {
		busy = true;
		error = '';
		for (const d of changed) {
			const resolution = editedResolution(d, edits[d.flag.flag_id], ambient);
			const key = JSON.stringify(resolution);
			try {
				previews[d.flag.flag_id] = { key, result: await dryRun({ case_key: caseKey, resolution: { flag_id: d.flag.flag_id, resolution } }) };
			} catch (e) {
				previews[d.flag.flag_id] = { key, result: describe(e) };
			}
		}
		busy = false;
	}

	async function save() {
		if (problem || !previewed) return;
		busy = true;
		error = '';
		try {
			await editCase(caseKey, {
				resolutions: changed.map((d) => ({ flag_id: d.flag.flag_id, resolution: editedResolution(d, edits[d.flag.flag_id], ambient) })),
				reason: reason.trim()
			});
			editing = false;
			notice = `Saved. The file is being rebuilt with the new units. Your sign-in and your reason are in the log.`;
			onChanged();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const shown = (id: string) => {
		const p = previews[id];
		if (!p) return '';
		if (typeof p.result === 'string') return p.result;
		const c = p.result.channels?.[0];
		return c ? displayRange(c.stat_min, c.stat_max, c.unit_si) : 'no converted values';
	};
	const inRange = (id: string) => {
		const p = previews[id];
		return p && typeof p.result === 'object' ? (p.result.channels?.[0]?.within_sanity ?? null) : null;
	};
</script>

<section class="panel" aria-labelledby="units-title">
	<div class="panel-header">
		<h2 id="units-title" class="panel-title">Units a person approved</h2>
		{#if decisions.length && !editing}
			<Button size="sm" variant="outline" onclick={start}><PencilIcon />Edit units</Button>
		{/if}
	</div>
	<div class="panel-body grid gap-3">
		{#if notice}<Notice tone="success">{notice}</Notice>{/if}
		{#if unchecked.length}
			<Notice tone="warning">
				{unchecked.length} of these units {unchecked.length === 1 ? 'was' : 'were'} applied by a rule and no person has checked {unchecked.length === 1 ? 'it' : 'them'}. Edit the units to check
				them: correct what is wrong, or confirm what is right, with your reason.
			</Notice>
		{/if}
		{#if decisions.length === 0}
			<p class="text-muted-foreground m-0 text-sm">No unit has been approved on this file yet.</p>
		{:else}
			<div class="overflow-x-auto rounded-md border">
				<table class="w-full text-sm" aria-label="Approved units">
					<thead>
						<tr class="bg-muted/60 text-muted-foreground text-left text-xs">
							<th class="px-2.5 py-1.5 font-medium">Column</th><th class="px-2.5 py-1.5 font-medium">Unit</th><th class="px-2.5 py-1.5 font-medium">Name</th>
							<th class="px-2.5 py-1.5 font-medium">Approved by</th>{#if editing}<th class="px-2.5 py-1.5 font-medium">Converted</th>{/if}
						</tr>
					</thead>
					<tbody>
						{#each decisions as d (d.flag.flag_id)}
							{@const e = edits[d.flag.flag_id]}
							<tr class="border-t align-top {editing && isChanged(d, e) ? 'bg-info-bg' : ''}">
								<td class="px-2.5 py-1.5 font-mono font-medium">{d.channel}</td>
								<td class="px-2.5 py-1.5">
									{#if editing && e}
										<select class="field h-8 w-52" aria-label="Unit of {d.channel}" bind:value={e.choiceId}>
											{#if d.choiceId === ''}<option value="">{d.label} (as approved)</option>{/if}
											{#each UNIT_GROUPS as g (g.quantity)}
												<optgroup label={g.label}>{#each g.choices as c (c.id)}<option value={c.id}>{c.label}</option>{/each}</optgroup>
											{/each}
										</select>
									{:else}{d.label}{/if}
								</td>
								<td class="px-2.5 py-1.5 font-mono text-xs">
									{#if editing && e}<input class="field h-8 w-52 font-mono" aria-label="Name of {d.channel}" bind:value={e.name} />{:else}{d.name}{/if}
								</td>
								<td class="text-muted-foreground px-2.5 py-1.5 text-xs">
									{#if d.appliedBy}
										<span class="text-warn font-medium">Nobody checked it</span><br />Applied by a rule saved by {d.appliedBy.ruleBy}, {when(d.appliedBy.ruleAt)}{d.appliedBy.ruleActive ? '' : ' (now switched off)'}
									{:else}
										{d.decidedBy ?? 'unknown'}<br />{when(d.decidedAt)}
										{#if d.proposedByRule}<br /><a href="/review/rules">proposed by a rule</a>{/if}
									{/if}
								</td>
								{#if editing}
									<td class="px-2.5 py-1.5 text-xs {inRange(d.flag.flag_id) === false ? 'text-hard' : inRange(d.flag.flag_id) ? 'text-ok' : ''}">{shown(d.flag.flag_id)}</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			{#if editing}
				{#if decisions.some((d) => isGaugeAfter(d, edits[d.flag.flag_id]))}
					<label class="field-label flex w-fit items-center gap-2"
						>Gauge readings are relative to
						<select class="field w-72" bind:value={ambient}>{#each AMBIENT_OPTIONS as o (o.value)}<option value={o.value}>{o.label}</option>{/each}</select>
					</label>
				{/if}
				<label class="grid gap-1">
					<span class="field-label">{confirming ? 'Why are these units right? (required, kept in the log with your sign-in)' : 'Why are you changing it? (required, kept in the log with your sign-in)'}</span>
					<textarea class="field" rows="2" bind:value={reason} placeholder="For example: the rig sheet says psig, not bar"></textarea>
				</label>
				<div class="flex flex-wrap items-center gap-2">
					<Button variant="outline" disabled={busy || !changed.length} onclick={previewChanges}>Preview {confirming ? 'the numbers' : 'changes'}</Button>
					<Button disabled={busy || !!problem || !previewed} onclick={save}>{confirming ? 'Confirm units' : 'Save change'}</Button>
					<Button variant="ghost" disabled={busy} onclick={() => (editing = false)}>Cancel</Button>
					<span class="text-muted-foreground text-xs" aria-live="polite">
						{problem ?? (previewed ? 'Ready to save.' : 'Preview the columns before saving.')}
					</span>
				</div>
			{:else}
				<div class="flex flex-wrap items-center gap-2 text-xs">
					<span class="text-muted-foreground">Want the questions asked again instead?</span>
					<ReopenButton {caseKey} flagIds={decisions.map((d) => d.flag.flag_id)} label="Reopen all columns" onDone={onReopened} />
				</div>
			{/if}
			{#if error}<Notice tone="error">{error}</Notice>{/if}
		{/if}
	</div>
</section>
