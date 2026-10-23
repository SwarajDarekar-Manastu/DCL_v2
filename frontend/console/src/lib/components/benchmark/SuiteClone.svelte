<script lang="ts">
	// Clone a suite under a new name: export it, copy the cases under new ids (<suite>.<case_id>), import them.
	import { ApiError, exportSuite, importSuite, type SuiteExport } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { clonePlan, type ClonePlan } from './suite_io';

	interface Props {
		suite: string;
		existing: string[];
		onDone: (message: string) => void;
		onCancel: () => void;
	}

	let { suite, existing, onDone, onCancel }: Props = $props();
	let source = $state<SuiteExport | null>(null);
	let name = $state('');
	let error = $state('');
	let busy = $state(false);

	$effect(() => {
		exportSuite(suite)
			.then((s) => (source = s))
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});

	let target = $derived(name.trim());
	let taken = $derived(existing.includes(target));
	let plan = $derived<ClonePlan | null>(source && target && !taken ? clonePlan(source, target) : null);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!plan || !plan.cases.length) return;
		busy = true;
		error = '';
		try {
			const counts = await importSuite(target, plan.cases);
			onDone(`Suite ${suite} cloned as ${target}: ${counts.created} cases.`);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<form class="grid gap-2 rounded-md border p-3 text-sm" aria-label="Clone suite {suite}" onsubmit={submit}>
	<label class="field-label grid gap-1"
		>New suite name for a copy of {suite}
		<input class="field text-foreground" bind:value={name} placeholder="{suite}-tuning" />
	</label>
	{#if taken}<p class="text-hard m-0 text-xs">A suite named {target} exists; pick another name.</p>{/if}
	{#if plan}
		<p class="m-0">
			Copies {plan.cases.length} cases as <code>{plan.cases[0]?.case_id ?? '…'}</code>{plan.cases.length > 1 ? ' and so on' : ''}.
		</p>
		{#if plan.skipped.holdOut.length}<p class="text-muted-foreground m-0 text-xs">Hold-out cases are never copied (DECISIONS 2026-10-22): {plan.skipped.holdOut.join(', ')}.</p>{/if}
		{#if plan.skipped.retired.length}<p class="text-muted-foreground m-0 text-xs">Retired, not copied: {plan.skipped.retired.join(', ')}.</p>{/if}
		{#if plan.skipped.idTooLong.length}<p class="text-warn m-0 text-xs">The new id would be over 80 characters, not copied: {plan.skipped.idTooLong.join(', ')}.</p>{/if}
	{/if}
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	<div class="flex gap-2">
		<Button type="submit" size="sm" disabled={busy || !plan?.cases.length}>Clone</Button>
		<Button size="sm" variant="ghost" disabled={busy} onclick={onCancel}>Cancel</Button>
	</div>
</form>
