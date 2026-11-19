# 3D Inspection — Priority 2 UI and functional regression checklist

**GitHub code prepared, not an assertion of live browser testing.**
Manual deployment is required; Dokploy Autodeploy stays OFF.
No database migrations, uploaded-model changes, or stored defect-coordinate changes
are included in this UI release. Keep the persistent \`chimney-uploads\` volume.

## A. Browser smoke tests (before accepting release)

| Scenario | Expected result |
| --- | --- |
| Admin login, dashboard, MEIL-GORTHA project | Same access and saved model as before |
| Existing 3D model and defect images | Load and stay linked to original saved findings |
| Manage Files menu | One toolbar button before Map Style; no permanent file-card row |
| Manage Files for Admin | 3TZ/ZIP, orthophoto, tileset JSON controls and upload-job status |
| Manage Files for Client | Inventory visible, no upload buttons |
| Upload status | Active/failed indicator remains visible on closed menu; menu shows detail |
| File safety | No test requires replacing a production model or deleting uploads |
| Map Style | Dark, Satellite, OSM remain mutually exclusive; dropdown closes on Escape/click outside |
| Compass while rotating model | Shows camera-heading N/E/S/W, 0–359°, 16-point readout |
| Compass when camera points vertically | Heading marked “held”, no needle spin |
| Defect List open/close | Compass moves into free canvas area and does not cover panel |
| Add Finding/Edit and drawing | Compass avoids form, controls and hints; on narrow screens can hide |
| Narrow screens (390, 768, 1024 pixels) | Toolbar scrolls horizontally; controls and form remain reachable |
| Fullscreen view | Compass repositions; controls remain accessible |
| Client Measure mode | Can measure without absent Admin button throwing a JS error |
| Measurement readout | Clearly says straight-line distance in metres |
| Project Overview, defect list filters | Existing information and actions remain accessible |
| Inspection PDF | Opens in a tab, or downloads if popup blocked |
| OpenStreetMap attribution | Visible link to OSM licence page in OSM mode; provider credits not suppressed |
| Existing KML export | Download keeps previous defect geometry |
| Upload processing failure/retry | Previous model still works; failure shown without deleting files |

## B. Unresolved accuracy issues — separate controlled investigation

1. **Defect-facing direction stability**: models.py currently derives the
   direction reference from a running average of defect locations when at
   least three are present. This means earlier displayed direction labels
   can change as new findings are added. Confirm a fixed surveyed structure
   centre before changing direction calculations. Compare viewer, server and
   PDF direction labels.
2. **Map-style alignment**: switching to Satellite/OSM applies a vertical
   modelMatrix translation. Saved defect WGS84 positions are not translated.
   Verify whether existing defect pins drift relative to the chimney before
   adjusting any georeferencing. Never rewrite stored coordinates
   automatically.
3. **Long-session rendering**: custom Cesium render loop calls resize and
   render continuously despite requestRenderMode. Profile CPU/GPU and large
   model cache on low-memory laptops and mobile devices before retuning.
4. **Model versions**: newly uploaded models are preserved separately and
   do not replace an active project model. A reviewed version-selection
   workflow is needed before allowing users to switch.
5. **Permission regression**: confirm an assigned Client User cannot
   access a different restricted project by URL or report API. Admin
   coverage alone does not prove project-specific access controls.

## C. Before and after deployment

- Preserve the latest checked backup of uploads and PostgreSQL.
- Do not change existing Dokploy volumes, environment variables or database.
- Build/Deploy the latest GitHub main only when ready for a controlled test.
- Run all relevant browser checks. On a failure, inspect browser Console
  and Docker logs. Do not delete or re-upload existing project files.
