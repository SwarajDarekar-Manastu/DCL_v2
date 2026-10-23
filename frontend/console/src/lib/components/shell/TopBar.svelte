<script lang="ts">
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { breadcrumbs } from './breadcrumbs';
	import ThemeToggle from './ThemeToggle.svelte';

	interface Props {
		pathname: string;
		search?: string;
		/** what the page has open, named in the last crumb */
		leaf?: string;
		/** true once the reviewer has moved inside the Console, so there is a page to go back to */
		canGoBack?: boolean;
		onBack?: () => void;
	}

	let { pathname, search = '', leaf = '', canGoBack = false, onBack }: Props = $props();
	let crumbs = $derived(breadcrumbs(pathname, search, leaf));
</script>

<header class="bg-background/80 sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b px-6 backdrop-blur">
	{#if canGoBack}
		<button
			type="button"
			class="text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:ring-ring -ml-2 inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
			onclick={() => onBack?.()}
		>
			<ArrowLeftIcon class="size-4" aria-hidden="true" />Back
		</button>
	{/if}
	<nav aria-label="Breadcrumb" class="min-w-0 flex-1">
		<ol class="m-0 flex list-none items-center gap-1.5 p-0 text-sm">
			{#each crumbs as crumb, i (i)}
				<li class="flex min-w-0 items-center gap-1.5">
					{#if i > 0}<ChevronRightIcon class="text-muted-foreground/60 size-3.5 shrink-0" aria-hidden="true" />{/if}
					{#if crumb.href}
						<a href={crumb.href} class="text-muted-foreground hover:text-foreground truncate no-underline hover:no-underline">{crumb.label}</a>
					{:else if i === crumbs.length - 1}
						<span class="text-foreground truncate font-medium" aria-current="page">{crumb.label}</span>
					{:else}
						<span class="text-muted-foreground truncate">{crumb.label}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>
	<ThemeToggle />
</header>
