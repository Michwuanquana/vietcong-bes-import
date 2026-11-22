# vietcong-bes-import

Import Vietcong (Ptero-Engine) `.BES` modelu do Blenderu 5.1 jednim skriptem: model,
spravne textury a kolize. Kolize a LOD se nemazou, jen jsou ve vychozim stavu skryte.

Stoji na addonu `vietcong_bes` (`%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\vietcong_bes`),
ktery skript za behu zapne pro danou session a opravi monkeypatchem. Addon samotny se nemeni.

## Pouziti

V Blenderu: Text Editor → otevrit `bes_import.py` → nastavit `BES_PATH` → Run Script.

Z prikazove radky:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --python bes_import.py -- "C:\Program Files (x86)\Autodesk\3dsMax8\meshes\LEVELS\RADIORELAY\04.BES"
```

Nastaveni nahore ve skriptu:

| Konstanta | Vyznam |
|---|---|
| `BES_PATH` | model, kdyz se nepreda argumentem |
| `GAME_ROOT` | koren dat hry; `None` = nejblizsi predek se slozkou `LEVELS` nebo `G` |
| `MODULATE_2X` | druha barevna mapa jako `base × map × 2` (jinak prosty multiply) |
| `NEW_SCENE` | importovat do nove sceny |

Vysledek je kolekce `BES <jmeno>` s podkolekcemi `<jmeno> – LOD` a
`<jmeno> – kolize a pomocné` (objekty `!`, `^K`, `^SF`, `^SK`, `@`). Obe jsou
skryte okem v Outlineru a vyrazene z renderu, objekty kolizi se kresli dratove.
Vlastnosti `bes_*` na objektech a materialech zustavaji kvuli zpetnemu exportu.

## LOD

LOD je v BES retez: zakladni objekt ma v User Defined Properties `Lod=20`, `Lod=60`,
`Lod=-1` (vzdalenosti prepnuti v metrech, `-1` = dal uz nic), dalsi urovne jsou jeho
deti s `Islod=1` (`bunkr_02` → `bunkr_02_lod_01` → `bunkr_02_lod_2`).

```python
show_lod(level=1)   # vsude 1. LOD (kde neni, posledni dostupny); level=0 zpet
show_lod()          # podle vzdalenosti od scene.camera, jako engine
```

Prepina viewport i render (hide_set + hide_render) a podle potreby zobrazi kolekci LOD.

## Stiny (LDT)

Predpocitane stiny/lightmapy nejsou v BES, ale v datech levelu:
`LEVELS\<level>\DATA\<scena>\LDT\*.LDT` (soubor na objekt, jmeno `XXXXXXXX_YYYYYYYYYYYYYYYY.LDT`)
a `SHADOWS.SHM`. Format zatim neni rozlusteny a skript je nenacita.
RADIORELAY v teto kopii dat slozku LDT nema.

## Co opravuje na addonu

1. **Vertexy se 2 UV sadami.** Addon rozpoznava skeletalni vertex podle velikosti
   (40 B = 1 vaha). Stejnou velikost ma obycejny vertex se dvema UV sadami (FVF `0x212`),
   takze se normala i UV ctou posunute a jako `UVMap` vznikne ve skutecnosti druha sada.
   Skript rozhoduje podle FVF typu pozice (`D3DFVF_XYZ` = bez vah).
1b. **Transformace vnorenych objektu.** BES uklada svetove matice (3ds Max node TM),
   addon je pouzije jako lokalni vuci rodici. U deti `Scene Root` (identita) se nic nestane,
   ale vnorene LOD pak lezi o 1×, 2× polohu rodice vedle (bunkr v z≈30, LOD1 v z≈60, LOD2 v z≈90).
   Skript nastavi `matrix_parent_inverse` tak, aby svetova matice odpovidala souboru.
2. **Textury z ciziho levelu.** Addon hleda rekurzivne a bere prvni shodu jmena.
   U modelu mimo slozku levelu tak `TLT_RADIO_ZEM.DDS` prijde z `LEVELS\CONQUEST_F`
   (krater) misto z `LEVELS\RADIORELAY`. Skript ze stejnojmennych souboru bere ten ze
   slozky, kde je nejvic textur tehoz modelu (pak blizkost k modelu, DDS pred ostatnimi,
   `_FOR_ALL` az nakonec).
3. **Jen prvni UV sada.** Skript importuje vsechny (`UVMap`, `UVMap2`, …) a kazde
   texture priradi jeji sadu podle poradi slotu ve vertexech.
4. **Druha mapa Standard materialu na Alpha.** U terenu je to velka barevna mapa
   (`TLT_BIG_PIK`) pres UV2; addon z ni dela pruhlednost. Skript ji modulaci
   prikresli k detailni texture.

## Materialy

- **Standard (0x1001):** UV sady jdou v poradi Ambient, Diffuse, Specular, Spec level,
  Glossiness, Self-illum, Filter, Bump, Reflection, Opacity (`0x002`), Displacement –
  pouze pritomne mapy. Diffuse = zaklad; mapa `0x002` = barevna modulace.
  Alfa jen kdyz ji diffuse textura opravdu ma.
- **PteroMat (0x1002):** UV sady Diffuse #1 → Diffuse #3 / Overlay multi → Diffuse #2 →
  Environment → Lightmap. Ground = zaklad, Multitexture = modulace, Overlay = mix pres
  svou alfu, Lightmap = multiply. Alfa podle typu pruhlednosti, dvoustrannost podle materialu.
- **PteroLayer (0x1004):** necha se, jak ho postavi addon.

## Neovereno

- Jak engine kombinuje druhou mapu (multiply vs. modulate 2x) – spec to neuvadi,
  `MODULATE_2X` je volba podle vizualni shody na RADIORELAY `04.BES`.
- Vyznam slotu `0x002`: addon (IDA) rika Opacity, [vc-spec](https://github.com/OpenVietcong/vc-spec/blob/master/doc/bes.md) Displacement.
- PteroMat kombinace na realnem modelu zatim netestovane (`04.BES` ma jen Standard).

## Overeno

`LEVELS\RADIORELAY\04.BES` (i kopie `meshes\04.BES`): 91 objektu, 16 LOD, 34 kolizi
a pomocnych. Kopec ma spravnou hlinu, travnate okraje a dry po granatech z BIG_PIK,
UV2 je temer rovinna projekce pres vsechny dily terenu.
