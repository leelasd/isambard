# The AMPAL Framework

This folder contains code for the AMPAL framework, which is used to represent
biomolecular structure in ISAMBARD. AMPAL classes for new biomolecules should be
added here to a file specifically for that molecule type. If a new molecule
class is added, a corresponding filter should be added to the PDBParser.

The `specifications` module is also included in this directory as specifications
directly inherit from the AMPAL framework.

# Work In Progress

## Documentation

### In Progress

### Finished

* `assembly_specs/`
    * `coiled_coil.py`
    * `nucleic_acid_duplex.py`
    * `solenoid.py`
* `polymer_specs/`
    * `helix.py`
    * `nucleic_acid_strand.py`
    * `ta_polypeptide.pyx`
* `assembly.py`
* `ampal_databases.py`
* `analyse_protein.py`
* `base_ampal.py`
* `interactions.py`
* `ligands.py`
* `non_cannonical.py`
* `nucleic_acid.py`
* `pdb_parser.py`
* `protein.py`
* `pseudo_atoms.py`
