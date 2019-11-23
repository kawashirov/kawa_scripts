from kawa_scripts import KawaMeshCombiner

KawaMeshCombiner.from_raw_config({
	'original_objects': {
		'Body': {},
	},
	'target_object': 'Body-Baked',
	'original_materials': {
		'Material_To_Ignore': {'atlas_ignore': True},
		'Material_To_DownScale': {'atlas_scale': 0.5, },
		'Material_To_UpScale': {'atlas_scale': 1.5, },
		'Material_With_Single_UV_Island': {'single_island': True, },
		'Material_To_Put_Into_Different_Material': {'atlas_target_material': 'AtlasFade', },
	},
	'atlas_target_material': 'AtlasOpaque',
	'atlas_textures': {'TEXTURE': {}, 'EMIT': {},},
	'atlas_epsilon': 4,
	'atlas_padding': 8,
}).run()
