"""
DRDM Testrig
"""

import math
from components import Plate, Outcome, ConstantRoller, HitResult, dry_test
from configuration import Config, AmmoType, Material, TYPICAL_PENETRATION, TYPICAL_CALIBER

def create_armor(c: Config, th: float = 1.0, m: Material = Material.STEEL, hp: int = 50, airg: float = 0.0) -> Plate:
    n: tuple = (0.0, 0.0, 1.0)
    return Plate(thickness=th, 
                     normal=n, 
                     material=m, 
                     health=hp, max_health=hp,
                     air_gap=airg,
                     config=c,
                    )
   
    return result
if __name__ == "__main__":
    conf = Config()
    armor_plate = create_armor(conf, 10.0, Material.STEEL, 100, 0.0)
    
    # cycle's all damage gradient flow and outcomes
    dry_test(armor_plate, 9.0, AmmoType.PISTOL, 9.0, 25)
    
    