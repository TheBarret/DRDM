"""
DRDM Testrig
"""

import math
from plate import Plate, Outcome, ConstantRoller, HitResult, dry_test
from configuration import Config, AmmoType, Material, TYPICAL_PENETRATION, TYPICAL_CALIBER

#from test import (run_all_tests, 
#                  TestHitResultContract, TestBackfaceCulling,
#                  TestEffectiveThickness, TestRicochet,
#                  TestPenetrationResidual, TestPlateDamage,
#                  TestOvermatch, TestAmmoTypes, TestRollProviderDeterminism,
#                  TestMultiHitSequence, TestCustomConditions,
#                  make_plate
#                  )

def create_plate(c: Config, th: float = 1.0, m: Material = Material.STEEL, hp: int = 50, airg: float = 0.0) -> Plate:
    n: tuple = (0.0, 0.0, 1.0)
    return Plate(thickness=th, 
                     normal=n, 
                     material=m, 
                     health=hp, max_health=hp,
                     air_gap=airg,
                     config=c,
                    )
def perform_hit(plate: Plate, ammo: AmmoType, angle: float = 0):

    P_in = TYPICAL_PENETRATION[ammo]
    caliber = TYPICAL_CALIBER[ammo]
    
    rad = math.radians(angle)
    d = (0, -math.sin(rad), -math.cos(rad))
    
    result = plate.hit(P_in, ammo, d, (0,0,0), caliber, 
                       shot_hash=hash((ammo, angle)), 
                       roller=ConstantRoller(1.0))
    
    print(f"    AMMO        : {ammo.name} | P: {P_in}mm | Cal: {caliber}mm | Angle: {angle}°")
    print(f"    PLATE       : {plate.thickness}mm {plate.material.value} | Health: {plate.health:.0f}/{plate.max_health}")
    print(f"    OUTCOME     : {result.outcome.value.upper()}")
    print(f"    Residual    : {result.residual_penetration:.1f}mm")
    print(f"    Damage      : {result.plate_damage:.1f} HP")
    print(f"    New health  : {result.new_health:.0f} HP")
    
    return result
if __name__ == "__main__":
    conf = Config()
    #run_all_tests()
    
    door = create_plate(conf, 8.0, Material.STEEL, 100, 0.0)
    dry_test(door, 5.56, AmmoType.RIFLE_BALL, 5.56, 40)
    