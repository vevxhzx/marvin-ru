from core.pc import organize

def test_plan_groups_montage_files_and_undo(tmp_path):
    root=tmp_path/'Монтаж'; root.mkdir()
    (root/'clip.mov').write_bytes(b'x'); (root/'music.wav').write_bytes(b'x'); (root/'edit.prproj').write_bytes(b'x')
    (root/'02_Исходники').mkdir(); (root/'02_Исходники'/'old.mov').write_bytes(b'x')
    p=organize.make_plan(root, tmp_path/'data')
    assert p['total']==4 and p['by_category']['02_Исходники/Видео']==2 and p['by_category']['05_Проекты']==1
    r=organize.apply_plan(p,tmp_path/'data'); assert len(r['moved'])==4
    u=organize.undo(tmp_path/'data'); assert len(u['moved'])==4 and (root/'edit.prproj').exists()

def test_sound_profile_uses_filename_semantics_and_custom_keywords(tmp_path):
    root=tmp_path/'Звук SFX'; root.mkdir()
    for n in ('footstep_soft.wav','UI_button_click.wav','rain_ambience.wav','boss_impact.wav','my_custom.wav'):
        (root/n).write_bytes(b'x')
    p=organize.make_plan(root,tmp_path/'data',None)
    assert p['profile']=='sound'
    assert p['by_category']['05_Шаги']==1
    assert p['by_category']['08_Интерфейс']==1
    assert p['by_category']['10_Природа']==1
    assert all('/SFX/' in m['dst'] for m in p['moves'])
    rules=tmp_path/'rules.json'; rules.write_text('{"keywords":{"13_Магия":["my_custom"]}}')
    p=organize.make_plan(root,tmp_path/'data',rules)
    assert p['by_category']['13_Магия']==1
