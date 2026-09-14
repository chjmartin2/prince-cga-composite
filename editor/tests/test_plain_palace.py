import json
from pathlib import Path
import tempfile
import unittest

from test_artwork_workspace import wall_dat
from test_composite_project import build_dat, image_resource
from artwork_workspace import ArtworkWorkspace, read_package, import_package
from prince_dat import DatArchive
from wall_profile import FAMILIES, OVERLAY_CONTRACT, WallSettings, wall_components
from wall_preview import render_recipe, overlay_inspector


class PlainPalaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'source';self.folder.mkdir()
        (self.folder/FAMILIES[0]).write_bytes(wall_dat())
        old=DatArchive.from_bytes(wall_dat(),FAMILIES[1])
        resources={r.resource_id:r.data for r in old.resources}
        header=bytearray(resources[1600]);header[0]=19;resources[1600]=bytes(header)
        resources[1618]=resources[1619]=resources[1601]
        resources[1603]=image_resource(4,2,0xb0,b'\x04\x10'*2)
        (self.folder/FAMILIES[1]).write_bytes(build_dat(sorted(resources.items())))
        self.ws=ArtworkWorkspace.open_folder(self.folder)

    def test_older_settings_keep_default_behavior_and_serialization(self):
        old=WallSettings.overlays()
        self.assertTrue(old.palace_overlays)
        self.assertNotIn('palace_overlays',old.to_dict())
        self.assertEqual(WallSettings.from_dict(old.to_dict()),old)
        new=WallSettings.overlays(palace_overlays=False)
        self.assertFalse(new.to_dict()['palace_overlays'])
        self.assertEqual(WallSettings.from_dict(new.to_dict()),new)
        for flag in (0,1,None,'false'):
            bad=new.to_dict();bad['palace_overlays']=flag
            with self.assertRaises(ValueError):WallSettings.from_dict(bad)
        legacy=WallSettings();legacy.palace_overlays=False
        with self.assertRaises(ValueError):legacy.to_dict()

    def test_palace_components_only_offer_bases_dungeon_unchanged(self):
        palace=wall_components(FAMILIES[1],OVERLAY_CONTRACT,palace_overlays=False)
        self.assertEqual([rid for rid,_,_ in palace],[1601,1602,1618,1619])
        self.assertTrue(all(role=='Base artwork' for _,_,role in palace))
        self.assertEqual(wall_components(FAMILIES[0],OVERLAY_CONTRACT),
                         wall_components(FAMILIES[0],OVERLAY_CONTRACT,palace_overlays=False))
        self.assertEqual(len(wall_components(FAMILIES[1],OVERLAY_CONTRACT)),19)

    def test_renderer_suppresses_palace_decals_but_keeps_dungeon_and_bases(self):
        commands=[['i',FAMILIES[1],1619,40,40,0],
                  ['i',FAMILIES[1],1603,40,40,16],
                  ['i',FAMILIES[0],1611,60,40,16]]
        expected=render_recipe([commands[0],commands[2]],self.ws.archives)
        disabled=WallSettings.overlays(palace_overlays=False)
        actual=render_recipe(commands,self.ws.archives,settings=disabled)
        self.assertEqual(actual.bits,expected.bits)
        self.assertEqual(actual.hits,expected.hits)
        self.assertEqual(actual.pick(82,40),(FAMILIES[1],1619))
        self.assertEqual(actual.pick(120,40),(FAMILIES[0],1611))
        enabled=render_recipe(commands,self.ws.archives,settings=WallSettings.overlays())
        self.assertEqual(enabled.pick(82,40),(FAMILIES[1],1603))
        with self.assertRaisesRegex(ValueError,'Palace overlays are disabled'):
            overlay_inspector(commands,FAMILIES[1],1603,self.ws.archives,settings=disabled)

    def test_disabled_setting_exports_without_deleting_any_artwork(self):
        self.ws.settings=WallSettings.overlays(palace_overlays=False)
        self.ws.recipes={'engine_contract':OVERLAY_CONTRACT,'palace_overlays':False,'rooms':[]}
        first=Path(self.temp.name)/'first.zip';second=first.with_name('second.zip')
        self.ws.export_zip(first)
        files,_,settings=read_package(first)
        self.assertFalse(settings.palace_overlays)
        for name in FAMILIES:
            self.assertEqual(files[name],(self.folder/name).read_bytes())
            self.assertEqual(files['patched/'+name],files[name])
        imported=import_package(first,Path(self.temp.name)/'imported')
        self.assertFalse(imported.settings.palace_overlays)
        imported.export_zip(second)
        self.assertEqual(first.read_bytes(),second.read_bytes())
        palace=DatArchive.from_bytes(files[FAMILIES[1]],FAMILIES[1])
        self.assertTrue(all(palace.resource_by_id(rid) for rid in range(1603,1618)))

    def test_workspace_rejects_conflicting_recipe_and_runtime_settings(self):
        (self.folder/'WALLS.JSN').write_text(json.dumps(WallSettings.overlays(palace_overlays=False).to_dict()))
        (self.folder/'PREVIEWS.JSON').write_text(json.dumps({'engine_contract':OVERLAY_CONTRACT,'rooms':[]}))
        with self.assertRaisesRegex(ValueError,'settings do not match'):
            ArtworkWorkspace.open_folder(self.folder)
        (self.folder/'PREVIEWS.JSON').write_text(json.dumps({'engine_contract':OVERLAY_CONTRACT,'palace_overlays':False,'rooms':[]}))
        self.assertFalse(ArtworkWorkspace.open_folder(self.folder).settings.palace_overlays)


if __name__=='__main__':unittest.main()
