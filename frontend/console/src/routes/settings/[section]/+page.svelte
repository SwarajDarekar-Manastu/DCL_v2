<script lang="ts">
	import PromptsPanel from '$lib/components/settings/PromptsPanel.svelte';
	import RedispatchPanel from '$lib/components/settings/RedispatchPanel.svelte';
	import SourcesPanel from '$lib/components/settings/SourcesPanel.svelte';
	import SettingsEditor from '$lib/components/settings/SettingsEditor.svelte';

	let { data } = $props();
	let section = $derived(data.section);
</script>

<div class="border-b px-5 py-4">
	<h2 class="m-0 text-base">{section.title}</h2>
	<p class="text-muted-foreground m-0 mt-1 max-w-[72ch]">{section.summary}</p>
</div>
<div class="space-y-5 px-5 py-4">
	<dl class="kv">
		<dt>When a change applies</dt>
		<dd>{section.apply}</dd>
	</dl>
	{#if section.id === 'sources'}<SourcesPanel />{/if}
	{#if section.id === 'routes'}<RedispatchPanel />{/if}
	{#if section.id === 'prompts'}<PromptsPanel />{:else}<SettingsEditor patterns={section.keys} title={section.title} />{/if}
</div>
