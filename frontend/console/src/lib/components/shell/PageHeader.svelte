<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		description?: string;
		/** right-aligned actions: buttons and links */
		children?: Snippet;
		/** shown under the title, full width (counts, tabs) */
		below?: Snippet;
	}

	let { title, description, children, below }: Props = $props();
</script>

<header class="mb-5 space-y-3">
	<div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
		<div class="min-w-0">
			<h1 class="m-0 text-lg leading-7">{title}</h1>
			{#if description}<p class="text-muted-foreground m-0 mt-0.5 max-w-[68ch]">{description}</p>{/if}
		</div>
		{#if children}<div class="flex flex-wrap items-center gap-2">{@render children()}</div>{/if}
	</div>
	{#if below}{@render below()}{/if}
</header>
