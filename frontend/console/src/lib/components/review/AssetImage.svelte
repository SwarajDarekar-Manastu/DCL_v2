<script lang="ts">
	import { presignAsset } from '$lib/api_endpoint';

	interface Props {
		uri: string;
		alt: string;
		class?: string;
	}

	let { uri, alt, class: className = '' }: Props = $props();
	let src = $state('');
	let failed = $state(false);

	$effect(() => {
		let cancelled = false;
		src = '';
		failed = false;
		presignAsset(uri)
			.then((asset) => !cancelled && (src = asset.url))
			.catch(() => !cancelled && (failed = true));
		return () => {
			cancelled = true;
		};
	});
</script>

{#if src}
	<img {src} {alt} class={className} />
{:else if failed}
	<span class="missing" title={uri}>image unavailable</span>
{/if}

<style>
	.missing {
		font-size: 0.75rem;
		opacity: 0.6;
	}
</style>
