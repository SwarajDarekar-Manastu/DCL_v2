<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	interface Props {
		title: string;
		description?: string;
		children?: Snippet;
		class?: string;
	}

	let { title, description, children, class: className }: Props = $props();
</script>

<div class={cn('rounded-lg border border-dashed px-6 py-10 text-center', className)}>
	<p class="m-0 font-medium">{title}</p>
	{#if description}<p class="text-muted-foreground m-0 mt-1">{description}</p>{/if}
	{#if children}<div class="mt-4 flex justify-center gap-2">{@render children()}</div>{/if}
</div>
