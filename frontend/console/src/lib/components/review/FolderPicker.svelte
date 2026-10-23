<script lang="ts">
	// Find the folder a rule covers by typing part of its path, instead of pasting a Graph item id.
	// With nothing typed it lists the folders that hold files waiting for a decision, most first.
	import { ApiError, listFolders, type FolderChoice } from '$lib/api_endpoint';
	import FolderIcon from '@lucide/svelte/icons/folder';
	import SearchIcon from '@lucide/svelte/icons/search';
	import Notice from '$lib/components/shell/Notice.svelte';

	interface Props {
		selected: FolderChoice | null;
		onPick: (folder: FolderChoice) => void;
	}

	let { selected, onPick }: Props = $props();
	let query = $state('');
	let found = $state<FolderChoice[]>([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		const text = query;
		loading = true;
		const timer = setTimeout(
			() =>
				listFolders(text)
					.then((list) => {
						found = list.items;
						error = '';
					})
					.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)))
					.finally(() => (loading = false)),
			text ? 250 : 0
		);
		return () => clearTimeout(timer);
	});

	const lastParts = (path: string) => {
		const parts = path.split('/');
		return { head: parts.slice(0, -1).join(' / '), leaf: parts[parts.length - 1] };
	};
</script>

<div class="grid gap-2">
	<label class="grid gap-1">
		<span class="field-label">Find the folder</span>
		<span class="relative block">
			<SearchIcon class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" aria-hidden="true" />
			<input class="field w-full pl-8" type="search" placeholder="Type part of its name, for example Injector 14" bind:value={query} />
		</span>
	</label>
	<p class="text-muted-foreground m-0 text-xs">
		{query.trim() ? 'Folders whose path contains your words.' : 'No search yet: these folders hold files waiting for a decision, most first.'}
	</p>
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	<ul class="m-0 grid max-h-64 list-none gap-1 overflow-y-auto p-0" aria-label="Folders" aria-busy={loading}>
		{#each found as folder (folder.folder_id)}
			{@const parts = lastParts(folder.path)}
			<li>
				<button
					type="button"
					class={[
						'hover:bg-muted flex w-full items-start gap-2.5 rounded-md border px-3 py-2 text-left',
						selected?.folder_id === folder.folder_id && 'border-foreground bg-muted'
					]}
					aria-pressed={selected?.folder_id === folder.folder_id}
					onclick={() => onPick(folder)}
				>
					<FolderIcon class="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden="true" />
					<span class="grid min-w-0 gap-0.5">
						<span class="truncate text-[13px] font-medium">{parts.leaf}</span>
						<span class="text-muted-foreground truncate text-xs">{parts.head}</span>
					</span>
					<span class="text-muted-foreground ml-auto shrink-0 text-right text-xs">
						{folder.files} file{folder.files === 1 ? '' : 's'}
						{#if folder.waiting}<br /><strong class="text-warn">{folder.waiting} waiting</strong>{/if}
					</span>
				</button>
			</li>
		{:else}
			{#if !loading}<li class="text-muted-foreground px-1 text-sm">{query.trim() ? 'No folder matches.' : 'No folder holds files that wait for a decision.'}</li>{/if}
		{/each}
	</ul>
</div>
