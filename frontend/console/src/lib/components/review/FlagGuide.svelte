<script lang="ts">
	import { Popover } from 'bits-ui';
	import HelpIcon from '@lucide/svelte/icons/circle-help';
	import type { FlagView } from '$lib/api_endpoint';
	import { guideFor } from './flag_guide';

	interface Props {
		flagType: FlagView['flag_type'];
	}
	let { flagType }: Props = $props();
	let guide = $derived(guideFor(flagType));
</script>

<Popover.Root>
	<Popover.Trigger
		class="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex size-6 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none"
		aria-label="What should I do with a {flagType} flag?"
	>
		<HelpIcon class="size-4" aria-hidden="true" />
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			side="bottom"
			align="start"
			sideOffset={6}
			class="bg-popover text-popover-foreground z-50 grid w-80 max-w-[90vw] gap-2 rounded-md border p-3 text-xs leading-5 shadow-md"
		>
			<p class="m-0"><strong>What is wrong:</strong> {guide.what}</p>
			<p class="m-0"><strong>You decide:</strong> {guide.decide}</p>
			<ul class="m-0 list-disc pl-4">
				{#each guide.choices as choice (choice)}<li>{choice}</li>{/each}
			</ul>
			<p class="text-muted-foreground m-0"><strong>Not sure?</strong> {guide.unsure}</p>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
