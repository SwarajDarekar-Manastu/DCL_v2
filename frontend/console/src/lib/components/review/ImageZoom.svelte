<script lang="ts">
	// One image full screen, scrollable to its foot. It takes focus so Escape closes it; the caller gives focus
	// back to whatever opened it (onClose).
	import AssetImage from './AssetImage.svelte';

	interface Props {
		uri: string | null;
		onClose: () => void;
	}

	let { uri, onClose }: Props = $props();
	let closeButton = $state<HTMLButtonElement | null>(null);
	$effect(() => {
		if (uri) closeButton?.focus();
	});
</script>

<svelte:window onkeydown={(e) => uri && e.key === 'Escape' && onClose()} />

{#if uri}
	<div class="fixed inset-0 z-50 overflow-auto bg-black/80 p-6" role="dialog" aria-modal="true" aria-label="Zoomed image">
		<button
			type="button"
			bind:this={closeButton}
			class="bg-background text-foreground focus-visible:ring-ring sticky top-0 z-10 float-right rounded-md border px-3 py-1 text-[13px] focus-visible:ring-2 focus-visible:outline-none"
			onclick={onClose}>Close (Esc)</button
		>
		<AssetImage {uri} alt="Zoomed image" class="mx-auto block h-auto max-w-full rounded bg-white" />
	</div>
{/if}
