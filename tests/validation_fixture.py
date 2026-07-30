"""Shared valid SIESTA input used by contextual-validation tests."""

BASE_FDF = """\
SystemName Validation fixture
SystemLabel validation_fixture
NumberOfAtoms 2
NumberOfSpecies 2
%block ChemicalSpeciesLabel
  1 6 C
  2 8 O
%endblock ChemicalSpeciesLabel
LatticeConstant 1.0 Ang
%block LatticeVectors
  8.0 0.0 0.0
  0.0 9.0 0.0
  0.0 0.0 18.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
  0.0 0.0 0.0 1
  1.2 0.0 0.0 2
%endblock AtomicCoordinatesAndAtomicSpecies
Mesh.Cutoff 350 Ry
%block kgrid.MonkhorstPack
  2 0 0 0.0
  0 3 0 0.0
  0 0 1 0.0
%endblock kgrid.MonkhorstPack
NetCharge 0
Spin non-polarized
MD.TypeOfRun CG
MD.Steps 0
"""
