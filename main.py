# native modules
import random

# Custom modules
# PyDASA modules
# data structures modules
# lists modules
from src.pydasa.datastruct.lists.arlt import ArrayList
from src.pydasa.datastruct.lists.sllt import SingleLinkedList
from src.pydasa.datastruct.lists.ndlt import Node, SLNode, DLNode
# hash tables modules
from src.pydasa.datastruct.tables.htme import MapEntry
from src.pydasa.datastruct.tables.scht import SCHashTable
from src.pydasa.datastruct.tables.scht import Bucket


# dimensional analysis modules
# config module
from src.pydasa.utils import config

# FDU modules
from src.pydasa.core.fundamental import Dimension

# FDU regex management
from src.pydasa.dimensional.framework import DimScheme

# Variable and Variable modules
from src.pydasa.core.parameter import Variable

# Dimensional Matrix Modelling module
from src.pydasa.dimensional.model import DimMatrix

# sensitivity analysis modules
from src.pydasa.analysis.scenario import DimSensitivity
from src.pydasa.handlers.influence import SensitivityHandler

# Monte Carlo Simulation modules
from src.pydasa.analysis.simulation import MonteCarloSim
from src.pydasa.handlers.practical import MonteCarloHandler

# from src.pydasa.dimensional.practical import MonteCarloHandler


def test_cmp(a, b) -> int:
    """Test comparison function."""
    if a < b:
        print(f"{a} < {b}")
        return -1
    elif a == b:
        print(f"{a} == {b}")
        return 0
    elif a > b:
        print(f"{a} > {b}")
        return 1
    else:
        raise TypeError(f"Invalid comparison between {type(a)} and {type(b)}")


# Define input distributions
def dist1(a, b):
    return random.uniform(a, b)


def dist2(mean, std):
    return random.gauss(mean, std)


a = ArrayList(iodata=[1, 2, 3],
              cmp_function=test_cmp)
print(a, "\n")

b = SingleLinkedList(iodata=[1, 2, 3])
print(b, "\n")
print(b.last, b.first, b.get(0), "\n")
print(b.index_of(2), b.index_of(4), "\n")
# print(b.pop_first(), b, "\n")
# n = DLNode(_data=1)
# print(n, "\n")

# m = MapEntry()
# print(m, "\n")

c = Bucket()
print(c, "\n")
_data = (
    {"_idx": 1, "_data": 1},
    {"_idx": 2, "_data": 2},
    {"_idx": 3, "_data": 3},
)
c = Bucket(iodata=_data)
print(c, "\n")
print(c.get(1), "\n")
print(c.get(2), "\n")

a = ArrayList(iodata=_data,
              cmp_function=test_cmp)
print(a, "\n")

ht = SCHashTable(iodata=_data)
print(ht, "\n")

nd = Node(_data=1)
print(nd, "\n")

nd = SLNode(_data=1)
print(nd, "\n")

nd.next = Node(_data=2)
print(nd, "\n")

dlnd = DLNode(_data=1)
print(dlnd, "\n")
dlnd.next = Node(_data=2)
dlnd.prev = Node(_data=0)
print(dlnd, "\n")

mp = MapEntry(_key="U_1",
              _value=1.0,)
print(mp, "\n")


# default regex for FDU
print("\n==== Default Regex ====")
print("\tDFLT_FDU_PREC_LT:", config.DFLT_FDU_PREC_LT)
print("\tDFLT_FDU_RE:", config.DFLT_FDU_RE)
print("\tDFLT_POW_RE:", config.DFLT_POW_RE)
print("\tDFLT_NO_POW_RE:", config.DFLT_NO_POW_RE)
print("\tDFLT_FDU_SYM_RE:", config.DFLT_FDU_SYM_RE)

# custom regex for FDU
print("\n==== Custom Regex ====")
print("\tWKNG_DFLT_FDU_PREC_LT:", config.WKNG_FDU_PREC_LT)
print("\tWKNG_FDU_RE:", config.WKNG_FDU_RE)
print("\tWKNG_POW_RE:", config.WKNG_POW_RE)
print("\tWKNG_NO_POW_RE:", config.WKNG_NO_POW_RE)
print("\tWKNG_FDU_SYM_RE:", config.WKNG_FDU_SYM_RE)

print("\n==== testing FDU ====")
fdu = Dimension()
print(fdu, "\n")

fdu = Dimension("Length",
                "Length of a physical quantity",
                1, "L", "PHYSICAL", "m")
print(fdu, "\n")

print("==== testing Variable ====")
v = Variable()
print(v, "\n")

p1 = Variable(name="U_1",
              description="Service Rate",
              _sym="U_{1}",
              _fwk="SOFTWARE",
              _idx=1,
              _cat="IN",
              _units="kPa",
              _dims="M*T^-2*L^-1",)
print(p1, "\n")

rm = DimScheme(_fwk="SOFTWARE",)
print(rm, "\n")


rm.update_global_config()
print(rm, "\n")

fdu_lt = [
    {"_idx": 0, "_sym": "M", "_fwk": "CUSTOM", "description": "Mass~~~~~~~~~~~~", "_unit": "kg", "name": "Mass"},
    {"_idx": 1, "_sym": "L", "_fwk": "CUSTOM", "description": "Longitude~~~~~~~~", "_unit": "m", "name": "Longitude"},
    {"_idx": 2, "_sym": "T", "_fwk": "CUSTOM", "description": "Time~~~~~~~~~~~~~", "_unit": "s", "name": "Time"},
]

rm = DimScheme(_fdus=fdu_lt, _fwk="CUSTOM")

rm.update_global_config()
print(rm, "\n")

# b = SingleLinkedList(iodata=fdu_lt)
# print(b.first, "\n", b.last, "\n")
# print(b, "\n")
# for fdu in b:
#     print(fdu, "\n")


DAModel = DimMatrix(_fwk="CUSTOM",
                    _idx=0,
                    _framework=rm)
print(DAModel, "\n")

# custom regex for FDU
print("\n==== Custom Regex ====")
print("\tWKNG_DFLT_FDU_PREC_LT:", config.WKNG_FDU_PREC_LT)
print("\tWKNG_FDU_RE:", config.WKNG_FDU_RE)
print("\tWKNG_POW_RE:", config.WKNG_POW_RE)
print("\tWKNG_NO_POW_RE:", config.WKNG_NO_POW_RE)
print("\tWKNG_FDU_SYM_RE:", config.WKNG_FDU_SYM_RE)

# Planar Channel Flow with a Moving Wall
# u = f(y, d, U, P, v)
# u: fluid velocity
# y: distance from the wall
# d: distance from the wall to the center of the channel (diameter)
# U: velocity of the wall
# P: pressure drop across the channel
# v: kinematic viscosity of the fluid

vars_lt = {
    "\\miu_{1}": Variable(_sym="\\miu_{1}",
                          _alias="miu_1",
                          _fwk="CUSTOM",
                          name="Fluid Velocity",
                          description="Fluid velocity in the channel",
                          relevant=True,
                          _idx=0,
                          _cat="OUT",
                          _units="m/s",
                          _dims="L*T^-1",
                          _min=0.0,
                          _max=15.0,
                          _mean=7.50,
                          _dev=0.75,
                          _std_units="m/s",
                          _std_min=0.0,
                          _std_max=15.0,
                          _std_mean=7.50,
                          _std_dev=0.75,
                          _step=0.1,
                          _dist_type="uniform",
                          _dist_params={"min": 0.0, "max": 15.0},
                          _dist_func=lambda: dist1(0.0, 15.0)),
    "y_{2}": Variable(_sym="y_{2}",
                      _alias="y_2",
                      _fwk="CUSTOM",
                      name="Distance from the wall",
                      description="Distance from the wall to the center of the channel",
                      relevant=True,
                      _idx=1,
                      _cat="IN",
                      _units="m",
                      _dims="L",
                      _min=0.0,
                      _max=10.0,
                      _mean=5.0,
                      _dev=0.50,
                      _std_units="m",
                      _std_min=0.0,
                      _std_max=10.0,
                      _std_mean=5.0,
                      _std_dev=0.50,
                      _step=0.1,
                      _dist_type="uniform",
                      _dist_params={"min": 0.0, "max": 10.0},
                      _dist_func=lambda: dist1(0.0, 10.0)),
    "d": Variable(_sym="d",
                  _alias="d",
                  _fwk="CUSTOM",
                  name="Channel diameter",
                  relevant=True,
                  description="Diameter of the channel",
                  _idx=2,
                  _cat="IN",
                  _units="m",
                  _dims="L",
                  _min=0.0,
                  _max=5.0,
                  _mean=2.5,
                  _dev=0.25,
                  _std_units="m",
                  _std_min=0.0,
                  _std_max=5.0,
                  _std_mean=2.5,
                  _std_dev=0.25,
                  _step=0.1,
                  _dist_type="uniform",
                  _dist_params={"min": 0.0, "max": 5.0},
                  _dist_func=lambda: dist1(0.0, 5.0)),
    "U": Variable(_sym="U",
                  _alias="U",
                  _fwk="CUSTOM",
                  name="Velocity of the wall",
                  relevant=True,
                  description="Velocity of the fluid wall",
                  _idx=3,
                  _cat="IN",
                  _units="m/s",
                  _dims="L*T^-1",
                  _min=0.0,
                  _max=15.0,
                  _mean=7.50,
                  _dev=0.75,
                  _std_units="m/s",
                  _std_min=0.0,
                  _std_max=15.0,
                  _std_mean=7.50,
                  _std_dev=0.75,
                  _step=0.1,
                  _dist_type="uniform",
                  _dist_params={"min": 0.0, "max": 15.0},
                  _dist_func=lambda: dist1(0.0, 15.0)),
    "P": Variable(_sym="P",
                  _alias="P",
                  _fwk="CUSTOM",
                  name="Channel Pressure Drop",
                  relevant=True,
                  description="Pressure drop across the channel",
                  _idx=4,
                  _cat="CTRL",
                  _units="Pa",
                  _dims="T^-2*L^1",
                  _min=0.0,
                  _max=100000.0,
                  _mean=50000.0,
                  _dev=5000.0,
                  _std_units="Pa",
                  _std_min=0.0,
                  _std_max=100000.0,
                  _std_mean=50000.0,
                  _std_dev=5000.0,
                  _step=100.0,
                  _dist_type="uniform",
                  _dist_params={"min": 0.0, "max": 100000.0},
                  _dist_func=lambda: dist1(0.0, 100000.0)),
    "v": Variable(_sym="v",
                  _alias="v",
                  _fwk="CUSTOM",
                  name="Fluid Viscosity",
                  relevant=True,
                  description="Kinematic viscosity of the fluid",
                  _idx=5,
                  _cat="CTRL",
                  _units="m^2/s",
                  _dims="L^2*T^-1",
                  _min=0.0,
                  _max=1.0,
                  _mean=0.5,
                  _dev=0.05,
                  _std_units="m^2/s",
                  _std_min=0.0,
                  _std_max=1.0,
                  _std_mean=0.5,
                  _std_dev=0.05,
                  _step=0.01,
                  _dist_type="uniform",
                  _dist_params={"min": 0.0, "max": 1.0},
                  _dist_func=lambda: dist1(0.0, 1.0)),
    "g": Variable(_sym="g",
                  _alias="g",
                  _fwk="CUSTOM",
                  name="Gravity",
                  description="Acceleration due to gravity",
                  _idx=6,
                  _cat="CTRL",
                  _units="m/s^2",
                  _dims="L*T^-2",),
    "f": Variable(_sym="f",
                  _alias="f",
                  _fwk="CUSTOM",
                  name="Fluid Frequency",
                  description="Fluid frequency",
                  _idx=7,
                  _cat="CTRL",
                  _units="Hz",
                  _dims="T^-1",),
}

print(type(vars_lt))
print("Dimensional relevance of the parameters:")
for p in vars_lt:
    print(p)

fdu_lt = [
    {"_idx": 0, "_sym": "Tt", "_fwk": "CUSTOM", "description": "Time~~~~~~~!!!~~~~~~"},
    {"_idx": 1, "_sym": "Mm", "_fwk": "CUSTOM", "description": "Mass~~~~~!!!!!~~~~~~~"},
    {"_idx": 2, "_sym": "Ll", "_fwk": "CUSTOM", "description": "Longitude~~~!!!!!!!~~~~~"},
]

print("Setting parameters for the dimensional analysis")
DAModel.variables = vars_lt
print(len(DAModel.variables), DAModel.variables, "\n")
print("Setting the relevance list for dimensional analysis")
DAModel.relevant_lt = vars_lt
print(len(DAModel.relevant_lt), DAModel.relevant_lt, "\n")

print(DAModel, "\n")

print(DAModel._n_var, "\n")

print(DAModel.relevant_lt, "\n")
print(len(DAModel.relevant_lt), "\n")
print(DAModel, "\n")
print(DAModel.working_fdus, "\n")

for k, relv in DAModel.relevant_lt.items():
    print("blaaaaa", k, "->", relv.idx, relv.cat, relv.sym, relv.name)
print(DAModel.output, "\n")

DAModel.create_matrix()
DAModel.solve_matrix()

print(DAModel._pivot_cols, "\n")
print(DAModel, "\n")

for k, v in vars(DAModel).items():
    print(f"{k}: {v}")
print("\n")

for k, v in DAModel.coefficients.items():
    pi = v
    print("key:", k, " --- ", pi.sym, "=", pi.pi_expr, "\n")

print("==== derive coefficients ===")
dev1 = "\\Pi_{0}*\\Pi_{1}"
dev2 = "\\Pi_{0}/\\Pi_{3}"
dev3 = "\frac{\\Pi_{0}}{\\Pi_{3}}"
pi_devs = [dev1, dev2, dev3]
for pi in pi_devs:
    
# print("=== Sensitivity Analysis: ===")
# temp = DAModel.coefficients["\\Pi_{1}"]
# print(f"Coefficients: {temp}\n")

# sen = DimSensitivity(_idx=0,
#                      _sym="S_{0}",
#                      _fwk="CUSTOM",
#                      name="Sensitivity",
#                      description="Sensitivity Analysis",
#                      _pi_expr=DAModel.coefficients["\\Pi_{1}"].pi_expr,
#                      _variables=list(DAModel.coefficients["\\Pi_{1}"].var_dims.keys()))
# print("=== Sensitivity: ===")
# print(sen, "\n")
# td = temp.var_dims
# # td["d"] = 5.05
# # td["y_{2}"] = 3.05
# td["U"] = 10.05
# td["\\miu_{1}"] = 0.05
# # td["P"] = 50000.05
# # sen.set_coefficient(DAModel.coefficients[1])

# print(td, "\n")
# r = sen.analyze_symbolically(td)
# print(rm, "\n")
# print([[0.1, 10.0]] * len(sen.variables))
# r = sen.analyze_numerically(list(td.keys()),
#                             [[0.1, 10.0]] * len(sen.variables))
# print(r, "\n")
# print(sen, "\n")

# print("\n=== Multiple Sensitivity Analysis: === \n")
# sena = SensitivityHandler(_idx=0,
#                           _sym="SA_{0}",
#                           _fwk="CUSTOM",
#                           name="Sensitivity Analysis",
#                           description="Sensitivity Analysis",
#                           _variables=vars_lt,
#                           _coefficients=DAModel.coefficients,)
# print(sena)

# print("=== Sym Analysis: ===")
# sena.analyze_symbolic(val_type="mean")

# for k, v in sena.results.items():
#     print(f"{k}: {v}")
# # print(sena.results, "\n")

# print("\n=== Num Analysis: ===")
# sena.analyze_numeric(n_samples=1000)

# for k, v in sena.results.items():
#     print(f"{k}: {v}")
#     for a, b in v.items():
#         print(f"\t{a}: {b}")

# print("Sensitivity Analysis Results:")
# # print(sena.analyses, "\n")

# for key, val in sena.results.items():
#     txt = f"{key}: {val}"
#     print(txt)

# # print(sena.results, "\n")
# # print(sena._coefficient_map.keys(), "\n")
# # print(sena._coefficient_map.get_entry("\\Pi_{0}"))
# # montecarlo
# print("\n=== Coefficient details: ===\n")
# for pi, coef in DAModel.coefficients.items():
#     print(f"Coefficient {pi} :=> {coef}\n")

# print("\n=== Monte Carlo Simulation: === \n")

# U = DAModel.variables["U"]
# miu = DAModel.variables["\\miu_{1}"]

# mc_dist = {
#     "U": lambda: dist1(U.std_min, U.std_max),
#     "\\miu_{1}": lambda: dist2(miu.std_mean, miu.std_dev),
# }

# dist_specs = {
#     "U": {
#         "dtype": U.dist_type,        # uniform
#         "params": U.dist_params,
#         "func": U.dist_func
#     },
#     "\\miu_{1}": {
#         "dtype": miu.dist_type,        # uniform
#         "params": miu.dist_params,
#         "func": miu.dist_func
#     }
# }

# i = 0
# while i < 10:
#     t1 = mc_dist["U"]()
#     t2 = mc_dist["\\miu_{1}"]()
#     print(f"Iteration {i}: U = {t1}, \\miu_{1} = {t2}")
#     i += 1
# _vars = list(DAModel.coefficients["\\Pi_{1}"].var_dims.keys())
# print("Vardims:", _vars)
# print(_vars.index("\\miu_{1}"))

# monte = MonteCarloSim()
# # print(monte, "\n")

# monte = MonteCarloSim(_idx=0,
#                       _sym="MC_{0}",
#                       _fwk="CUSTOM",
#                       name="Monte Carlo Simulation",
#                       description="Monte Carlo Simulation~~~~~!!!",
#                       _pi_expr=DAModel.coefficients["\\Pi_{1}"].pi_expr,
#                       _variables=DAModel.variables,
#                       _distributions=dist_specs,
#                       _iterations=1000,)
# monte.set_coefficient(DAModel.coefficients["\\Pi_{1}"])
# print(monte, "\n")

# monte.run()
# print("Monte Carlo Simulation Results:")
# for k, v in monte.statistics.items():
#     print(f"{k}: {v}")
# print("Mean:", monte.mean)
# print("Variance:", monte.variance)
# # print("Summary:", monte.summary)
# # a = monte.export_results().keys()
# print("Confidence result keys:", monte.export_results().keys())

# print("Confidence report:", monte.get_confidence_interval(0.95))

# print("\n=== monte carlo handler ===")
# # Create a handler
# mchandler = MonteCarloHandler(_sym="MCH_{0}",
#                               _fwk="CUSTOM",
#                               name="Monte Carlo Handler",
#                               description="Monte Carlo Handler for simulations",
#                               _variables=DAModel.relevant_lt,
#                               _coefficients=DAModel.coefficients)
# print(mchandler, "\n")
# mchandler._create_distributions()
# # print(mchandler._distributions)
# mchandler._create_simulations()
# print(mchandler._simulations.keys())
# for k, v in mchandler._simulations.items():
#     print(f"Simulation dist = {k}:\n\t{v._distributions}")
# mchandler.simulate(n_samples=100)

# for pi, results in mchandler._results.items():
#     for k, v in results.items():
#         if k == "statistics":
#             print(f"Coefficient: {pi}")
#             print(f"Result for {k}: {v}")
#         else:
#             print(f"Other result for {k}: {v.shape}")
