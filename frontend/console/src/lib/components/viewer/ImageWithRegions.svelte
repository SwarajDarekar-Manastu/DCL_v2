<script lang="ts">
	import type { ViewerRegion } from '$lib/api_endpoint';
	import { cn } from '$lib/utils';

	interface Props {
		src: string;
		alt: string;
		width: number;
		height: number;
		regions: ViewerRegion[];
	}

	let { src, alt, width, height, regions }: Props = $props();
	const pct = (value: number) => `${(value * 100).toFixed(3)}%`;
	const label = (region: ViewerRegion) => region.label + (region.confidence == null ? '' : ` (confidence ${region.confidence.toFixed(2)})`);
	// Status colors: cited passage = info (blue), handwriting = purple, flagged region = hard (red).
	const KIND = {
		cited: 'border-info bg-info/10',
		handwriting: 'border-handwriting bg-handwriting/10 border-dashed',
		flag: 'border-hard bg-hard/10'
	} as const;
</script>

<!-- Regions use normalized coordinates, so percentages keep them on target at any rendered size. -->
<div class="bg-background relative w-full overflow-hidden rounded-md border shadow-sm" style="aspect-ratio: {width} / {height}">
	<img class="block h-full w-full" {src} {alt} {width} {height} />
	{#each regions as region, i (i)}
		<div
			class={cn(
				'absolute rounded-[2px] border-2 shadow-[0_0_0_1px_var(--background)]',
				KIND[region.kind]
			)}
			data-testid="region"
			data-kind={region.kind}
			style="left: {pct(region.bbox[0])}; top: {pct(region.bbox[1])}; width: {pct(region.bbox[2] - region.bbox[0])}; height: {pct(region.bbox[3] - region.bbox[1])}"
			title={label(region)}
			role="note"
			aria-label="{region.kind} region: {label(region)}"
		></div>
	{/each}
</div>
