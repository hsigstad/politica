from sqlalchemy import Column, Integer, String, BigInteger, Date, Numeric
from sqlalchemy import Float, Text, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.mysql import MEDIUMTEXT


Base = declarative_base()    


class Politico(Base):
    __tablename__ = 'politico'
    cpf = Column(BigInteger, primary_key=True, autoincrement=False)
    politico = Column(String(255))
    race = Column(String(255))
    nationality = Column(String(255))
    gender = Column(String(255))
    birthdate = Column(Date)    
    birth_municipio_id = Column(Integer)
    birth_estado = Column(String(2))
    def __repr__(self):
        return "Politico(%s)" % (str(self.name))
    
class Candidato(Base):
    __tablename__ = 'candidato'
    id = Column(Integer, primary_key=True)
    cpf = Column(BigInteger, ForeignKey('politico.cpf'))
    estado = Column(String(2))
    municipio_id = Column(Integer)
    year = Column(Integer)
    office = Column(String(255))
    round = Column(Integer)
    votes = Column(Integer)
    elected = Column(String(255))
    electeddummy = Column(Integer)
    margin = Column(Float)
    party = Column(String(255))
    coalition = Column(String(255))
    campaignexpenditure = Column(Integer)
    occupation = Column(String(255))
    education = Column(String(255))
    marital_status = Column(String(255))
    suplementar = Column(Integer)
    def __repr__(self):
        return "Candidato(%s)" % (str(self.name))


class Eleicao(Base):
    __tablename__ = 'eleicao'
    id = Column(Integer, primary_key=True) 
    year = Column(Integer)
    round = Column(Integer)
    electiondate = Column(Date)
    electiontype = Column(String(10))
    def __repr__(self):
        return "Eleicao({}, {})".format(self.year, self.round)
    
