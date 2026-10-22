<script lang="ts">
	// The one page frame: header (title, description, actions), optional filter bar, content, and an
	// optional details panel on the right. Every Console screen uses it so spacing and widths agree.
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';
	import PageHeader from './PageHeader.svelte';

	interface Props {
		title: string;
		description?: string;
		/** right-aligned header actions */
		actions?: Snippet;
		/** full-width row under the title: counts, tabs, summary */
		below?: Snippet;
		/** filter bar above the content */
		filters?: Snippet;
		/** details panel, right of the content on wide screens */
		details?: Snippet;
		/** "full" fills the window (work screens); "default" caps at 1400px; "narrow" at 960px (forms) */
		width?: 'default' | 'full' | 'narrow';
		children: Snippet;
		class?: string;
	}

	let { title, description, actions, below, filters, details, width = 'default', children, class: className }: Props = $props();
	const WIDTH = { default: 'max-w-[1400px]', full: 'max-w-none', narrow: 'max-w-[960px]' } as const;
</script>

<div class={cn('mx-auto w-full px-6 pt-5 pb-10', WIDTH[width], className)}>
	<PageHeader {title} {description} {below} children={actions} />
	{#if filters}
		<div class="mb-4 flex flex-wrap items-end gap-3" role="group" aria-label="Filters">{@render filters()}</div>
	{/if}
	{#if details}
		<div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
			<div class="min-w-0">{@render children()}</div>
			<aside class="min-w-0 xl:sticky xl:top-[calc(var(--sticky-top,0px)+1.25rem)]" aria-label="Details">{@render details()}</aside>
		</div>
	{:else}
		{@render children()}
	{/if}
</div>
