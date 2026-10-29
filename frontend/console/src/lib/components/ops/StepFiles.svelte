<script lang="ts">
	// The files in one pipeline step, opened from the Ops page's step counts.
	import { Dialog } from 'bits-ui';
	import XIcon from '@lucide/svelte/icons/x';
	import { ApiError, getStepFiles, type Step, type StepFiles } from '$lib/api_endpoint';
	import { ageText } from '$lib/components/review/format';
	import { STEP_HINT, STEP_LABEL } from './file_steps';

	let { step = $bindable(null) }: { step?: Step | null } = $props();
	let page = $state<StepFiles | null>(null);
	let error = $state('');
	const int = (n: number) => n.toLocaleString('en-US');
	const folder = (path: string | null) => (path?.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '');

	$effect(() => {
		const asked = step;
		page = null;
		error = '';
		if (!asked) return;
		getStepFiles(asked)
			.then((p) => {
				if (step === asked) page = p;
			})
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});
</script>

<Dialog.Root open={step !== null} onOpenChange={(open) => !open && (step = null)}>
	<Dialog.Portal>
		<Dialog.Overlay class="fixed inset-0 z-50 bg-black/60" />
		<Dialog.Content
			class="bg-background text-foreground fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100vh-2rem)] w-[min(80rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-xl border shadow-2xl outline-none"
		>
			{#if step}
				<header class="flex items-start justify-between gap-4 border-b px-6 py-4">
					<div class="grid gap-1">
						<Dialog.Title class="m-0 text-lg font-semibold">{STEP_LABEL[step]}{page ? ` · ${int(page.total)}` : ''}</Dialog.Title>
						<Dialog.Description class="text-muted-foreground m-0 text-sm">{STEP_HINT[step]}</Dialog.Description>
					</div>
					<Dialog.Close class="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex size-8 items-center justify-center rounded-md focus-visible:ring-2 focus-visible:outline-none" aria-label="Close the list">
						<XIcon class="size-4" aria-hidden="true" />
					</Dialog.Close>
				</header>
				<div class="min-h-0 overflow-y-auto">
					{#if error}
						<p class="text-hard m-0 p-6 text-sm">{error}</p>
					{:else if !page}
						<p class="text-muted-foreground m-0 p-6 text-sm">Loading…</p>
					{:else if page.files.length === 0}
						<p class="text-muted-foreground m-0 p-6 text-sm">No files in this step.</p>
					{:else}
						{#if page.total > page.files.length}
							<p class="text-muted-foreground m-0 px-6 pt-3 text-sm">The first {int(page.files.length)} of {int(page.total)}.</p>
						{/if}
						<table class="data-table">
							<thead><tr><th>File</th><th>Route</th><th>Updated</th><th>Where it is</th></tr></thead>
							<tbody>
								{#each page.files as f, i (f.doc_id ?? `${f.path}#${i}`)}
									<tr>
										<td>
											{#if f.doc_id}<a href="/docs/{f.doc_id}/viewer">{f.name}</a>{:else}{f.name}{/if}
											{#if folder(f.path)}<div class="text-muted-foreground text-xs">{folder(f.path)}</div>{/if}
										</td>
										<td class="font-mono text-xs">{f.route ?? ''}</td>
										<td class="text-sm whitespace-nowrap" title={f.updated_at ?? ''}>{f.updated_at ? `${ageText(f.updated_at)} ago` : ''}</td>
										<td class="text-sm">{f.detail ?? ''}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</div>
			{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>
