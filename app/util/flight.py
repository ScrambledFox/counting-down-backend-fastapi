from enum import Enum

from app.schemas.v1.airport import AirportCode


class AirportCodeType(Enum):
    IATA = "IATA"
    ICAO = "ICAO"


def get_airport_code_type(airport_code: AirportCode) -> AirportCodeType:
    return AirportCodeType.IATA if len(airport_code) == 3 else AirportCodeType.ICAO
