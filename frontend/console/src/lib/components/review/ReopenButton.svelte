<script lang="ts">
	// Take decisions back so the file is decided again: any flag type, any age, with a written reason that is
	// kept with the signed-in reviewer in the audit log (POST /review/cases/{key}/reopen).
	import { ApiError, reopenCase } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { MIN_REASON } from './decisions';

	interface Props {
		caseKey: string;
		flagIds: string[];
		label?: string;
		/** called once the decisions are reopened (the file is then in the review queue again) */
		onDone: () => void;
	}

	let { caseKey, flagIds, label = 'Reopen', onDone }: Props = $props();
	let asking = $state(false);
	let reason = $state('');
	let busy = $state(false);
	let error = $state('');
	let valid = $derived(reason.trim().length >= MIN_REASON);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!valid) return;
		busy = true;
		error = '';
		try {
			await reopenCase(caseKey, { flag_ids: flagIds, reason: reason.trim() });
			asking = false;
			reason = '';
			onDone();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

{#if !asking}
	<Button variant="ghost" size="xs" onclick={() => (asking = true)}>{label}</Button>
{:else}
	<form class="flex flex-wrap items-center gap-1.5" onsubmit={submit} aria-label="Reopen with a reason">
		<input class="field h-7 w-60" placeholder="Why reopen it? (required)" aria-label="Reason for reopening" bind:value={reason} />
		<Button type="submit" size="xs" disabled={busy || !valid}>Reopen</Button>
		<Button type="button" variant="ghost" size="xs" onclick={() => (asking = false)}>Cancel</Button>
		{#if error}<Notice tone="error">{error}</Notice>{/if}
	</form>
{/if}
