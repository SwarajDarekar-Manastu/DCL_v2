<script lang="ts">
	// Import a suite file (the format of Export): read it, say what it holds, then POST it.
	import { ApiError, importSuite, type SuiteExport } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { parseSuiteFile } from './suite_io';

	interface Props {
		onDone: (message: string) => void;
	}

	let { onDone }: Props = $props();
	let file = $state<SuiteExport | null>(null);
	let error = $state('');
	let busy = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	const readText = (blob: Blob) =>
		new Promise<string>((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(String(reader.result ?? ''));
			reader.onerror = () => reject(reader.error);
			reader.readAsText(blob);
		});

	async function read(event: Event) {
		error = '';
		file = null;
		const chosen = (event.currentTarget as HTMLInputElement).files?.[0];
		if (!chosen) return;
		const parsed = parseSuiteFile(await readText(chosen));
		if (parsed.ok) file = parsed.value;
		else error = `${chosen.name}: ${parsed.error}`;
	}

	async function submit() {
		if (!file) return;
		busy = true;
		error = '';
		try {
			const counts = await importSuite(file.suite, file.cases);
			onDone(`Suite ${file.suite} imported: ${counts.created} created, ${counts.versioned} new versions, ${counts.unchanged} unchanged.`);
			file = null;
			if (input) input.value = '';
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="flex flex-wrap items-center gap-2" role="group" aria-label="Import suite">
	<label class="text-sm">
		<span class="sr-only">Suite file</span>
		<input bind:this={input} type="file" accept="application/json,.json" class="text-xs" onchange={read} aria-label="Suite file" />
	</label>
	{#if file}
		<span class="text-sm">{file.cases.length} cases for suite <strong>{file.suite}</strong>{file.exported_at ? `, exported ${file.exported_at.slice(0, 10)}` : ''}</span>
		<Button size="sm" disabled={busy} onclick={submit}>Import</Button>
		<Button size="sm" variant="ghost" disabled={busy} onclick={() => ((file = null), input && (input.value = ''))}>Cancel</Button>
	{/if}
	{#if error}<Notice tone="error" class="w-full">{error}</Notice>{/if}
</div>
