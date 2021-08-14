# Downloads, Installation and Contacts
You can find everything related to this on a **[Github page](https://github.com/kawashirov/kawa_scripts)**.

`kawa_scripts` distributed as [Blender addon](https://docs.blender.org/manual/en/latest/advanced/scripting/addon_tutorial.html).
Addon should work on all verisons of Blender **from 2.80**, but **2.9x** is recommended.

You can find ready-to-install zipped addon on **[Releases page](https://github.com/kawashirov/kawa_scripts/releases)**.

To install you should go *Edit* > *Preferences* > *Add-ons*, click "*Install*" and select downloaded `.zip` archive.

![addons_page.png](https://i.imgur.com/uwdhl2v.png)

There is no any auto-updaters, if you want to upgrade `kawa_scripts`,
you should remove old version and install fresh one.

After installation, you can use all features programmatically without UI
by `import kawa_sripts` in Python Console or in `.py` text assets. 

### You can contact me here:
* Discord: `kawashirov#8363`
* VRChatRU Discord: [`mxHxk3B`](https://discord.gg/mxHxk3B)
* Twitter: [@kawashirov](https://twitter.com/kawashirov)
* Github: [kawashirov](https://github.com/kawashirov)
* VRChat: [kawashirov](https://vrchat.com/home/user/usr_62eb0df9-7b6d-480f-be82-fd1b945e98aa)

Please follow and support me on ko-fi too ❤

[![SupportMe_blue@60.png](https://i.imgur.com/b8bSntD.png)](https://ko-fi.com/kawashirov)

# Features
TODO ¯\_(ツ)_/¯

# How to use. Example of VRChat world: Russian Apartament: Хрущевка
My world ["Russian Apartament: Хрущевка" for VRChat](https://vrchat.com/home/world/wrld_a5aa8c95-1903-4ce1-a2df-0027964e4b3e)
uses this addon for baking large hierarchy of objects and 400+ materials
into few combined objects and single 4K x 4K PBR atlas!

And every time I change something in my project I don't need to set up anything: just
[running building script `bake2.py`](https://gist.github.com/kawashirov/76041f63f2be37c398df9c89fec30e5c),
waiting a few minutes, and my `.fbx` + `.png` atlases are ready to be put into Unity project.

You can use this building script as reference. Most of the features in `kawa_scripts`
I implemented for my projects, especially this one.

There is some utility functions in `bake2.py`, but main are `make_working_hierarchy` and `make_atlas`.

### First one, `make_working_hierarchy`
Does the following:

* Duplicates entire hierarchy of raw Objects into separate scene.
* Applies proper objects naming to duplicated hierarchy.
* Instantiates all collections (with proper objects naming).
* Makes single-user objects
* Converts non-mesh (Curves) objects into mesh-objects
* Instantiates all material slots (Object-overrides)
* Applies all modifiers of Objects.
* Applies all transform scales
* Combines some parts of hierarchy with a lots of small objects into few large objects.

All these complex operations made using `instantiator.BaseInstantiator` and `combiner.BaseMeshCombiner`.

For example this complex hierarchy:
	
![combiner_example_before.png](https://i.imgur.com/hA9Od1G.png)

flattens to this:

![combiner_example_after.png](https://i.imgur.com/7QcrBDT.png)


### Second one, `make_atlas`
Packs most of the materials into large texture atlas:
[<img alt="KhrushchyovkaAtlas-D+A.png" width="480" height="480" src="https://i.imgur.com/7T1sE37.jpg"/>](https://i.imgur.com/7T1sE37.jpg)

(Image scaled down to 2k because of hosting limits.)

There is almost full support of PBR layers such as Normals, Metallic, Smoothness, Emission.
Atlas is baked using Blender's bake features,
so you can build own complex PBR materials using Cycles shader nodes
and bake them together with other materials into same texture atlas.

