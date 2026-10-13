"""Existing protocol classes/types are available from the installed API."""


def test_protocols_and_existing_types_are_exported_without_version_change():
    import qraft.api as api
    names = ('EosProtocol', 'ElectronicAnalysisProtocol', 'ElectronicPropertiesProtocol',
             'ElectronicStateSource', 'PreparedElectronicProperties',
             'BandPathSpec', 'DosSpec', 'PdosSpec', 'PropertySpec', 'SurfaceProtocol')
    assert api.API_VERSION == '1.0'
    assert all(name in api.__all__ and getattr(api, name) is not None for name in names)
    assert 'parse_bands' not in api.__all__
