<script lang="ts">
	import type { ViewerRegion } from '$lib/api_endpoint';

	interface Props {
		src: string;
		alt: string;
		width: number;
		height: number;
		regions: ViewerRegion[];
	}

	let { src, alt, width, height, regions }: Props = $props();
	const pct = (value: number) => `${(value * 100).toFixed(3)}%`;
</script>

<!-- Regions use normalized coordinates, so percentages keep them on target at any rendered size. -->
<div class="frame" style="aspect-ratio: {width} / {height}">
	<img {src} {alt} {width} {height} />
	{#each regions as region, i (i)}
		<div
			class="region region-{region.kind}"
			data-testid="region"
			style="left: {pct(region.bbox[0])}; top: {pct(region.bbox[1])}; width: {pct(region.bbox[2] - region.bbox[0])}; height: {pct(region.bbox[3] - region.bbox[1])}"
			title={region.label + (region.confidence == null ? '' : ` (confidence ${region.confidence.toFixed(2)})`)}
		></div>
	{/each}
</div>

<style>
	.frame {
		position: relative;
		width: 100%;
		max-width: 60rem;
		background: var(--surface);
		border: 1px solid var(--border);
	}
	img {
		display: block;
		width: 100%;
		height: 100%;
	}
	.region {
		position: absolute;
		border: 2px solid;
		border-radius: 2px;
		pointer-events: auto;
	}
	.region-cited {
		border-color: #f59e0b;
		background: rgb(245 158 11 / 0.18);
	}
	.region-handwriting {
		border-color: #8b5cf6;
		background: rgb(139 92 246 / 0.12);
	}
	.region-flag {
		border-color: #ef4444;
		background: rgb(239 68 68 / 0.12);
	}
</style>
