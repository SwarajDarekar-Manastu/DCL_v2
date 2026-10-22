<script lang="ts">
	import { cn } from '$lib/utils';
	import { SETTINGS_SECTIONS } from './sections';

	interface Props {
		current: string;
	}

	let { current }: Props = $props();
</script>

<nav aria-label="Settings sections">
	<ul class="m-0 list-none space-y-0.5 p-0">
		{#each SETTINGS_SECTIONS as section (section.id)}
			<li>
				<a
					href="/settings/{section.id}"
					aria-current={section.id === current ? 'page' : undefined}
					class={cn(
						'text-muted-foreground hover:bg-muted hover:text-foreground flex h-8 items-center rounded-md px-2.5 text-sm no-underline transition-colors hover:no-underline',
						section.id === current && 'bg-muted text-foreground font-medium'
					)}>{section.title}</a
				>
			</li>
		{/each}
	</ul>
</nav>
