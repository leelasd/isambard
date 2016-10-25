from collections import OrderedDict
import itertools
import warnings

import numpy

from buff import PyAtomData, BuffForceField, score_ampal
from ampal.interactions import find_CH_pi_interactions, find_CH_pi_acceptor, find_CH_pis_in_list
from ampal.ampal_databases import element_data
from tools.components import atomic_mass
from tools.components import component_category, component_covalent_bonds, component_pi_systems
from tools.isambard_warnings import NotParameterisedWarning
from tools.geometry import distance, Quaternion, centre_of_mass, rmsd
from settings import global_settings


def cap(v, l):
    s = str(v)
    return s if len(s) <= l else s[-l:]


def find_atoms_within_distance(atoms, cutoff_distance, point):
    """Returns atoms within the distance from the point."""
    return [x for x in atoms if distance(x, point) <= cutoff_distance]


def centre_of_atoms(atoms, mass_weighted=True):
    """ Returns centre point of any list of atoms.

    Parameters
    ----------
    atoms : list
        List of AMPAL atom objects.
    mass_weighted : bool
        If True returns centre of mass, otherwise just geometric centre of points.

    Returns
    -------
    numpy array
    """
    points = [x._vector for x in atoms]
    if mass_weighted:
        masses = [x.mass for x in atoms]
    else:
        masses = []
    return centre_of_mass(points=points, masses=masses)

def radius_of_gyration(atoms):
    """Returns the radius of gyration of a set of atoms
        """
    c_o_m = centre_of_atoms(atoms,mass_weighted=False)
    r = [distance(r,c_o_m) for r in atoms]
    return sum(r) / len(r)

def write_pdb(residues, chain_id=' ', alt_states=False, strip_states=False):
    """Writes a pdb file for a list of residues.

    Parameters
    ----------
    residues : list
        List of Residue objects.
    chain_id : str
        String of the chain id, defaults to ' '.
    alt_states : bool
        If true, include all occupancy states of residues, else outputs primary state only.
    strip_states : bool
        If true, remove all state labels from residues. Only use with alt_states false.

    Returns
    -------
    pdb_str : str
        String of the PDB file.
    """
    pdb_atom_col_dict = global_settings['ampal']['pdb_atom_col_dict']
    out_pdb = []
    if len(str(chain_id)) > 1:
        poly_id = ' '
    else:
        poly_id = str(chain_id)
    for monomer in residues:
        if (len(monomer.states) > 1) and alt_states and not strip_states:
            atom_list = itertools.chain(*[x[1].items() for x in sorted(monomer.states.items())])
        else:
            atom_list = monomer.atoms.items()
        if 'chain_id' in monomer.tags:
            poly_id = monomer.tags['chain_id']
        for atom_t, atom in atom_list:
            if strip_states:
                state_label = ' '
            elif (atom.tags['state'] == 'A') and (len(monomer.states) == 1):
                state_label = ' '
            else:
                state_label = atom.tags['state']
            atom_data = {
                'atom_number': '{:>5}'.format(cap(atom.id, 5)),
                'atom_name': '{:<4}'.format(cap(pdb_atom_col_dict[atom_t], 4)),
                'alt_loc_ind': '{:<1}'.format(cap(state_label, 1)),
                'residue_type': '{:<3}'.format(cap(monomer.mol_code, 3)),
                'chain_id': '{:<1}'.format(cap(poly_id, 1)),
                'res_num': '{:>4}'.format(cap(monomer.id, 4)),
                'icode': '{:<1}'.format(cap(monomer.insertion_code, 1)),
                'coord_str': '{0:>8.3f}{1:>8.3f}{2:>8.3f}'.format(*[x for x in atom]),
                'occupancy': '{:>6.2f}'.format(atom.tags['occupancy']),
                'temp_factor': '{:>6.2f}'.format(atom.tags['bfactor']),
                'element': '{:>2}'.format(cap(atom.element, 2)),
                'charge': '{:<2}'.format(cap(atom.tags['charge'], 2))
            }
            if monomer.is_hetero:
                pdb_line_template = (
                    'HETATM{atom_number} {atom_name}{alt_loc_ind}{residue_type} {chain_id}{res_num}'
                    '{icode}   {coord_str}{occupancy}{temp_factor}          {element}{charge}\n')
            else:
                pdb_line_template = (
                    'ATOM  {atom_number} {atom_name}{alt_loc_ind}{residue_type} {chain_id}{res_num}'
                    '{icode}   {coord_str}{occupancy}{temp_factor}          {element}{charge}\n')
            out_pdb.append(pdb_line_template.format(**atom_data))
    return ''.join(out_pdb)


class BaseAmpal(object):

    @property
    def pdb(self):
        """Runs make_pdb in default mode."""
        return self.make_pdb()

    @property
    def centre_of_mass(self):
        """ Returns the centre of mass as a numpy.array. (all atoms included in calculation). """
        elts = set([x.element for x in self.get_atoms()])
        masses_dict = {e: element_data[e]['atomic mass'] for e in elts}
        points = [x._vector for x in self.get_atoms()]
        masses = [masses_dict[x.element] for x in self.get_atoms()]
        return centre_of_mass(points=points, masses=masses)

    def is_within(self, cutoff_dist, point):
        """Returns all atoms in the ampal object that are within the cut-off distance from the input point."""
        return find_atoms_within_distance(self.get_atoms(), cutoff_dist, point)

    def get_atoms(self):
        raise NotImplementedError

    def make_pdb(self):
        raise NotImplementedError

    def assign_force_field(self, ff, mol2=False):
        """Assigns force field parameters to Atoms in the AMPAL object.

        Parameters
        ----------
        ff: BuffForceField
            The force field to be used for scoring.
        mol2: bool
            If true, mol2 style labels will also be used.
        """
        if hasattr(self, 'ligands'):
            atoms = self.get_atoms(ligands=True, inc_alt_states=True)
        else:
            atoms = self.get_atoms(inc_alt_states=True)
        for atom in atoms:
            w_str = None
            if atom.element == 'H':
                continue
            elif atom.ampal_parent.mol_code in ff:
                if atom.res_label in ff[atom.ampal_parent.mol_code]:
                    a_ff_id = (atom.ampal_parent.mol_code, atom.res_label)
                elif atom.res_label in ff['WLD']:
                    a_ff_id = ('WLD', atom.res_label)
                else:
                    w_str = '{} atom is not parameterised in the selected force field for {} residues,' \
                            ' this will be ignored.'.format(atom.res_label, atom.ampal_parent.mol_code)
            elif atom.res_label in ff['WLD']:
                a_ff_id = ('WLD', atom.res_label)
            elif mol2 and (atom.ampal_parent.mol_code.capitalize() in ff['MOL2']):
                a_ff_id = ('MOL2', atom.res_label.capitalize())
            else:
                if not mol2:
                    w_str = '{} ({}) atom is not parameterised in the selected residue force field. ' \
                            'Try activating the heavy atom force field (haff).'.format(atom.element, atom.res_label)
                else:
                    w_str = '{} ({}) atom is not parameterised in the selected force field.'.format(atom.element,
                                                                                                 atom.res_label)
            if w_str:
                warnings.warn(w_str, NotParameterisedWarning)
            atom._ff_id = a_ff_id
        self.tags['assigned_ff'] = True
        return

    def update_ff(self, ff, mol2=False, force_ff_assign=False):
        """Manages assigning the force field parameters.

        The aim of this method is to avoid unnecessary assignment of the
        force field.

        Parameters
        ----------
        ff: BuffForceField
            The force field to be used for scoring.
        mol2: bool
            If true, mol2 style labels will also be used.
        force_ff_assign: bool
            If true, the force field will be completely reassigned, ignoring the
            cached parameters.
        """
        aff = False
        if force_ff_assign:
            aff = True
        elif 'assigned_ff' not in self.tags:
            aff = True
        elif not self.tags['assigned_ff']:
            aff = True
        if aff:
            self.assign_force_field(ff, mol2=mol2)
        return

    def get_internal_energy(self, assign_ff=True, ff=None, mol2=False, force_ff_assign=False, threshold=1.1):
        """Calculates the internal energy of the AMPAL object.

        This method is assigned to the buff_internal_energy property,
        using the default arguments.

        Parameters
        ----------
        assign_ff: bool
            If true the force field will be updated if required.
        ff: BuffForceField
            The force field to be used for scoring.
        mol2: bool
            If true, mol2 style labels will also be used.
        force_ff_assign: bool
            If true, the force field will be completely reassigned, ignoring the
            cached parameters.
        threshold: float
            Cutoff distance for assigning interactions that are covalent bonds.

        Returns
        -------
        BUFF_score: BUFFScore
            A BUFFScore object with information about each of the interactions and
            the atoms involved.
        """
        if not ff:
            ff = global_settings['buff']['force_field']
        if assign_ff:
            self.update_ff(ff, mol2=mol2, force_ff_assign=force_ff_assign)
        return score_ampal(self, ff, threshold=threshold, internal=True)

    buff_internal_energy = property(get_internal_energy)

    def rotate(self, angle, axis, point=None, radians=False, inc_alt_states=True):
        q = Quaternion.angle_and_axis(angle=angle, axis=axis, radians=radians)
        for atom in self.get_atoms(inc_alt_states=inc_alt_states):
            atom._vector = q.rotate_vector(v=atom._vector, point=point)
        return

    def translate(self, vector, inc_alt_states=True):
        vector = numpy.array(vector)
        for atom in self.get_atoms(inc_alt_states=inc_alt_states):
            atom._vector += vector
        return

    def rmsd(self, other, backbone=False):
        assert type(self) == type(other)
        if backbone and hasattr(self, 'backbone'):
            points1 = self.backbone.get_atoms()
            points2 = other.backbone.get_atoms()
        else:
            points1 = self.get_atoms()
            points2 = other.get_atoms()
        points1 = [x._vector for x in points1]
        points2 = [x._vector for x in points2]
        return rmsd(points1=points1, points2=points2)


class Polymer(BaseAmpal):
    def __init__(self, monomers=None, ligands=None, polymer_id=' ', molecule_type='', ampal_parent=None, sl=2):
        """A container that holds monomer type objects, this is how polypeptides are represented in ISAMBARD.

        Has a simple hierarchy: A Polymer contains one or more Monomer.

        Parameters
        ----------
        monomers : Monomer or [Monomer]
            Monomer or list containing Monomer objects to form the Polymer().
        polymer_id : str
            An ID that the user can use to identify the Polymer. This is used when generating a pdb file using
            Polymer().pdb

        Raises
        ------
        TypeError
            Polymer objects can only be initialised empty, using a Monomer or a list of Monomers.
        """
        if monomers:
            if isinstance(monomers, Monomer):
                self._monomers = [monomers]
            elif isinstance(monomers, list) and isinstance(monomers[0], Monomer):
                self._monomers = list(monomers)
            else:
                raise TypeError(
                    'Polymer objects can only be initialised empty, using a Monomer or a list of Monomers.')
        else:
            self._monomers = []
        self.id = str(polymer_id)
        self.ampal_parent = ampal_parent
        self.molecule_type = molecule_type
        self.ligands = ligands
        self.tags = {}
        self.sl = sl

    def __add__(self, other):
        if isinstance(other, Polymer):
            merged_polymer = self._monomers + other._monomers
        else:
            raise TypeError('Only Polymer objects may be merged with a Polymer.')
        return Polymer(monomers=merged_polymer, polymer_id=self.id)

    def __len__(self):
        return len(self._monomers)

    def __getitem__(self, item):
        if isinstance(item, str):
            id_dict = {str(m.id): m for m in self._monomers}
            return id_dict[item]
        elif isinstance(item, int):
            return self._monomers[item]
        else:
            return Polymer(self._monomers[item], polymer_id=self.id)

    def __repr__(self):
        return '<Polymer containing {} {}>'.format(
            len(self._monomers), 'Monomer' if len(self._monomers) == 1 else 'Monomers')

    def append(self, item):
        if isinstance(item, Monomer):
            self._monomers.append(item)
        else:
            raise TypeError('Only Monomer objects can be appended to an Polymer.')
        return

    def extend(self, polymer):
        if isinstance(polymer, Polymer):
            self._monomers.extend(polymer)
        else:
            raise TypeError('Only Polymer objects may be merged with a Polymer using unary operator "+".')
        return

    def get_monomers(self, ligands=True):
        if ligands and self.ligands:
            monomers = self._monomers + self.ligands._monomers
        else:
            monomers = self._monomers
        return iter(monomers)

    def get_atoms(self, ligands=True, inc_alt_states=False,ignore_hydrogens=False):
        """Flat list of all the Atoms in the Polymer.

        Parameters
        ----------
        inc_alt_states : bool
            If true atoms from alternate conformations are included rather
            than only the "active" states.

        Returns
        -------
        atoms : itertools.chain
            Returns an iterator of all the atoms. Convert to list if you
            require indexing.
        """
        if ligands and self.ligands:
            monomers = self._monomers + self.ligands._monomers
        else:
            monomers = self._monomers
        atoms = itertools.chain(*(list(m.get_atoms(inc_alt_states=inc_alt_states,ignore_hydrogens=ignore_hydrogens)) for m in monomers))
        return atoms

    def relabel_monomers(self, labels=None, start=None):
        """Relabels the component Monomers either in numerical order or using a list of labels.

        Parameters
        ----------
        labels : list
            A list of new labels.

        start : int
            New starting value for the monomers. Used for relabelling chains from a particular residue number.

        Raises
        ------
        ValueError
            Raised if the number of labels does not match the number of component Monoer objects.
        ValueError
            Raised if labels and start are both set
        ValueError
            Raised if start is not an integer

        """
        if labels and start:
            raise ValueError('Cannot use both labels= and start=')

        elif labels:
            if len(self._monomers) == len(labels):
                for monomer, label in zip(self._monomers, labels):
                    monomer.id = str(label)
            else:
                raise ValueError('Number of Monomers ({}) and number of labels ({}) must be equal.'.format(
                    len(self._monomers), len(labels)))
        elif start:

            if type(start) != int:
                raise ValueError('Start value is not an integer')
            for i, monomer in enumerate(self._monomers):
                monomer.id = str((start-1)+i+1)

        else:
            for i, monomer in enumerate(self._monomers):
                monomer.id = str(i + 1)
        return

    def relabel_atoms(self, start=1):
        """Relabels all Atoms in numerical order, offset by the start parameter."""
        counter = start
        for atom in self.get_atoms():
            atom.id = counter
            counter += 1
        return

    def relabel_all(self):
        """Relabels all monomers and atoms using default labeling."""
        self.relabel_monomers()
        self.relabel_atoms()
        return

    def make_pdb(self, alt_states=False, inc_ligands=True):
        """Generates a PDB string for the Polymer.

        Returns
        -------
        pdb_str : str
            String of the pdb for the Polymer. Generated using information from the component Monomers.
        """
        if any([False if x.id else True for x in self._monomers]):
            self.relabel_monomers()
        if self.ligands and inc_ligands:
            monomers = self._monomers + self.ligands._monomers
        else:
            monomers = self._monomers
        pdb_str = write_pdb(monomers, self.id, alt_states=alt_states)
        return pdb_str

    def get_reference_coords(self):
        """ Gets list of coordinates of all reference atoms in the Polymer.

        Returns
        -------
        ref_coords : list(numpy.array)
            List has the same length as the Polymer.
            The first, second and third elements of array i contain the x, y and z
            coordinates of the i-th reference atom.
        """
        return [x[x.reference_atom].array for x in self._monomers]

    def get_CH_pi_interactions(self, donor_codes=None, donor_categories=None, acceptor_codes=None,
                               dist_cutoff=3.5, angle_cutoff=55, proj_cutoff=2):
        """ List of CH-pi interactions within an AMPAL chain, as AMPAL CH_pi objects."""
        CH_pi_dict = find_CH_pis_in_list([x for x in self.get_monomers()], donor_codes=donor_codes,
                                         donor_categories=donor_categories, acceptor_codes=acceptor_codes,
                                         dist_cutoff=dist_cutoff, angle_cutoff=angle_cutoff, proj_cutoff=proj_cutoff)
        return [item for sublist in CH_pi_dict.values() for item in sublist]


class Monomer(BaseAmpal):
    def __init__(self, atoms=None, monomer_id=' ', ampal_parent=None):
        """Object containing Atoms, this is how residues are represented in ISAMBARD.

        Parameters
        ----------
        atoms : OrderedDict or {OrderedDict}
            OrderedDict containing Atoms for the Monomer. OrderedDict is used to maintain the order items
            were added to the dictionary.
        monomer_id : str
            String used to identify the residue.
        """
        if type(atoms) is dict:
            self.states = atoms
            self._active_state = sorted(self.states.keys())[0]
        elif type(atoms) is OrderedDict:
            self.states = dict(A=atoms)
            self._active_state = 'A'
        else:
            # Sets up dummy states which should be filled later
            self.states = {'A': OrderedDict()}
            self._active_state = 'A'
        self.id = str(monomer_id)
        self.ampal_parent = ampal_parent
        self.tags = {}

    def __getitem__(self, key):
        return self.atoms.__getitem__(key)

    def __setitem__(self, key, value):
        self.atoms.__setitem__(key, value)

    def __iter__(self):
        return iter(self.atoms.values())

    def __len__(self):
        return len(self.atoms)

    def __repr__(self):
        return '<Monomer containing {} {}>'.format(len(self.atoms), 'Atom' if len(self.atoms) == 1 else 'Atoms')

    @property
    def active_state(self):
        return self._active_state

    @active_state.setter
    def active_state(self, value):
        if value in self.states.keys():
            self._active_state = value
        else:
            raise KeyError(
                'Selected alternate state is not available please use: {}'.format(list(self.states.keys())))

    @property
    def atoms(self):
        return self.states[self.active_state]

    @atoms.setter
    def atoms(self, atom_dict):
        if type(atom_dict) != OrderedDict:
            raise TypeError('Atoms dict must be of the type OrderedDict.')
        if self.states:
            self.states[self.active_state] = atom_dict

    def get_monomers(self):
        return [self]

    def get_atoms(self, inc_alt_states=False, ignore_hydrogens=False):
        if inc_alt_states:
            if ignore_hydrogens:
                return itertools.chain(*[x[1].values() for x in sorted(list(self.states.items())) if x.element != "H"])
            else:
                return itertools.chain(*[x[1].values() for x in sorted(list(self.states.items()))])
        elif ignore_hydrogens:
            return itertools.chain([x for x in self.atoms.values() if x.element != "H"])

        else:
            return self.atoms.values()

    def make_pdb(self):
        pdb_str = write_pdb([self], ' ' if not self.ampal_parent else self.ampal_parent.id)
        return pdb_str

    @property
    def category(self):
        comp_cat = component_category(self.mol_code)
        return comp_cat

    @property
    def is_solvent(self):
        if component_category(self.mol_code, ask_unknown=False) == 'solvent':
            return True
        else:
            return False

    def comp_covalent_bonds(self, atom_a='', atom_b=''):
        """ Gives dictionary of covalent bonds involving atoms a and b within ideal, free version of monomer."""
        comp_cov_bonds = component_covalent_bonds(self.mol_code, atom_a=atom_a, atom_b=atom_b)
        return comp_cov_bonds

    @property
    def comp_pi_systems(self):
        """ Gives dictionary of pi system labels with atom lists in ideal version of monomer."""
        comp_pi_sys = component_pi_systems(self.mol_code)
        return comp_pi_sys

    def close_monomers(self, group, cutoff=4.0, sc_only=False):
        """Returns a list of Monomers from within a cut off distance of the Monomer

        Parameters
        ----------
        group: BaseAmpal or Subclass
            Group to be search for Monomers that are close to this Monomer.
        cutoff: float
            Distance cut off.
        sc_only :  Bool
            If true, only includes side-chain atoms of nearby Residues.

        Returns
        -------
        nearby_residues: [Monomers]
            List of Monomers within cut off distance.
        """
        nearby_residues = []
        for self_atom in self.atoms.values():
            nearby_atoms = group.is_within(cutoff, self_atom)
            for res_atom in nearby_atoms:
                if res_atom.ampal_parent in nearby_residues:
                    continue
                if sc_only:
                    try:
                        if res_atom not in res_atom.ampal_parent.side_chain:
                            continue
                    except AttributeError:
                        continue
                nearby_residues.append(res_atom.ampal_parent)
        return nearby_residues

    def environment(self, cutoff=4.0, include_self=False, include_neighbours=True, inter_chain=True,
                    include_ligands=False, include_solvent=False, sc_only=False):
        """Returns the residues with any atom within a defined distance of any atom of the monomer.

        Parameters
        ----------
        cutoff : float
            Maximum inter-atom distance for residue to be included. Defaults to 4.
        include_self : bool
            If true, includes monomer in output list of residues. Default false.
        include_neighbours : bool
            If false, does not return monomers at i-1, i+1 positions in same chain as Monomer.
        inter_chain : bool
            If false, only includes nearby monomers in the same chain as the Monomer.
        include_ligands : bool
            If true, Monomers classed as ligands but not identified as solvent will be included in the environment.
        include_solvent : bool
            If true, Monomers classed as categorised as solvent will be included in the environment.
        sc_only :  Bool
            If true, only includes side-chain atoms of nearby Residues. Overrides include solvent and include_ligands.

        Raises
        ------
        AttributeError
            Raised if Monomer has no ampal_parent defined.
        """
        if self.ampal_parent:
            if self.ampal_parent.ampal_parent and inter_chain:
                group = self.ampal_parent.ampal_parent
            else:
                group = self.ampal_parent
        else:
            raise AttributeError('Monomer is not part of a group i.e. it has no ampal_parent.')
        if not include_ligands and not include_solvent:
            group = Polymer(monomers=[x for x in group.get_monomers(ligands=False)])
        elif not include_solvent:
            group = Polymer(monomers=[x for x in group.get_monomers() if not x.is_solvent])
        elif not include_ligands:
            solvent_list = [x for x in group.get_monomers() if x.is_solvent]
            group = Polymer(monomers=[x for x in group.get_monomers(ligands=False)] + solvent_list)
        nearby_residues = self.close_monomers(group, cutoff=cutoff, sc_only=sc_only)
        if include_self:
            if self not in nearby_residues:
                nearby_residues.append(self)
        elif self in nearby_residues:
            del(nearby_residues[nearby_residues.index(self)])
        if not include_neighbours:
            for residue in nearby_residues:
                if residue.ampal_parent.id != self.ampal_parent.id:
                    continue
                if residue.id == str(int(self.id) + 1) or residue.id == str(int(self.id) - 1):
                    del(nearby_residues[nearby_residues.index(residue)])
        return nearby_residues

    def CH_pi_interactions(self, as_donor=True, as_acceptor=True, acceptor_codes=[], donor_codes=[], dist_cutoff=3.5,
                           angle_cutoff=55, proj_cutoff=2, inter_chain=True):
        """ A list of CH-pi interactions that a monomer is engaged in, as AMPAL CH_pi objects."""
        all_chpis = []
        if as_donor:
            all_chpis.extend(find_CH_pi_interactions(self, acceptor_codes=acceptor_codes, dist_cutoff=dist_cutoff,
                                                     angle_cutoff=angle_cutoff, proj_cutoff=proj_cutoff,
                                                     inter_chain=inter_chain))
        if as_acceptor:
            all_chpis.extend(find_CH_pi_acceptor(self, donor_codes=donor_codes, dist_cutoff=dist_cutoff,
                                                 angle_cutoff=angle_cutoff, proj_cutoff=proj_cutoff,
                                                 inter_chain=inter_chain))
        return all_chpis


class Atom(object):
    """Object containing atomic coordinates and element information. Used to represent atoms in ISAMBARD."""

    def __init__(self, coordinates, element, atom_id=' ', res_label=None, occupancy=1.0, bfactor=1.0, charge=' ',
                 state='A', ampal_parent=None):
        self._vector = numpy.array(coordinates)
        self.id = atom_id
        self.res_label = res_label
        self.element = element
        self.ampal_parent = ampal_parent
        self.tags = {
            'occupancy': occupancy,
            'bfactor': bfactor,
            'charge': charge,
            'state': state
        }
        self._ff_id = None

    def __repr__(self):
        return "<{} Atom{}. Coordinates: ({:.3f}, {:.3f}, {:.3f})>".format(
            element_data[self.element.title()]['name'], '' if not self.res_label else ' ({})'.format(self.res_label),
            self.x, self.y, self.z)

    def __getitem__(self, item):
        return self._vector[item]

    def __setitem__(self, item, value):
        self._vector[item] = value
        return

    def __sub__(self, other):
        """Subtracts coordinates and returns a numpy.array. Objects themselves remain unchanged."""
        assert isinstance(other, Atom)
        return self._vector - other._vector

    def __add__(self, other):
        """Adds coordinates and returns a numpy.array. Objects themselves remain unchanged."""
        assert isinstance(other, Atom)
        return self._vector + other._vector

    @property
    def array(self):
        """Converts the atomic coordinate to a numpy.array"""
        return self._vector

    @property
    def x(self):
        return self._vector[0]

    @property
    def y(self):
        return self._vector[1]

    @property
    def z(self):
        return self._vector[2]

    @property
    def mass(self):
        return atomic_mass(self.element)

    @property
    def unique_id(self):
        chain = self.ampal_parent.ampal_parent.id
        residue = self.ampal_parent.id
        return chain, residue, self.id

    def rotate(self, angle, axis, point=None, radians=False):
        q = Quaternion.angle_and_axis(angle=angle, axis=axis, radians=radians)
        self._vector = q.rotate_vector(v=self._vector, point=point)
        return

    def translate(self, vector):
        self._vector += numpy.array(vector)
        return


__author__ = 'Christopher W. Wood, Kieran L. Hudson'
