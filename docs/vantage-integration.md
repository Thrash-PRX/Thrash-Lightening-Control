# Vantage integration investigation

Reviewed 2026-11-06. Thrash is a standalone application, not a Lenovo Vantage extension.

Official sources reviewed:
- https://docs.lenovocdrt.com/guides/lcv/ describes deployment and administration.
- https://docs.lenovocdrt.com/guides/lcv/configuration/ documents ADMX policies and warranty inventory through WMI.
- https://vantagepro.lenovo.com/portal/vantage_pro_sdk.html concerns commercial tablets, not the Windows consumer Vantage lighting UI.

No public, supported API for registering a third-party lighting page or effect provider in Windows Lenovo Vantage was found in these sources. This is a bounded research conclusion, not proof that a private partner program cannot exist. Commercial Vantage management policies do not provide such an extension point.

The existing controller uses reflection into installed IdeaNotebookAddin assemblies. That is a private compatibility bridge and can break with Lenovo updates; it is not an officially supported SDK or genuine plugin integration. Do not install files into Vantage, modify its manifests, inject code, or redistribute proprietary assemblies. Genuine integration remains deferred until Lenovo supplies a documented contract and permission to use it.

Validation still required: test bridge reconnect, Fn+Space, idle wake, and native Off/Dim/Bright transitions on a compatible LOQ. Software tests cannot establish these hardware results.
