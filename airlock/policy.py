"""Bounded, typed CEL subset evaluated by cel-python; trusted YAML configuration."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
import celpy
from celpy import celtypes
from lark import Tree
import yaml
from yaml.tokens import AliasToken, AnchorToken
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .models import digest

TYPES = {'tool': str, 'resource': str, 'principal': str, 'operation': str,
         'changed_rows': int, 'matched_rows': int}
CEL_TYPES = {str: celtypes.StringType, int: celtypes.IntType, bool: celtypes.BoolType}


class Rule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    expression: str = Field(min_length=1,max_length=512)
    decision: Literal['pass','block','need_approval']


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    version: str = Field(min_length=1,max_length=64)
    rules: list[Rule] = Field(max_length=32)


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def mapping(loader,node,deep=False):
    result={}
    for key,value in node.value:
        name=loader.construct_object(key,deep=deep)
        if not isinstance(name,str) or name in result:
            raise ValueError('duplicate or non-string YAML key')
        result[name]=loader.construct_object(value,deep=deep)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)


def check_type(node,depth=0):
    """Reject CEL outside a finite boolean/comparison subset before evaluation."""
    if depth>60 or not isinstance(node,Tree):
        raise ValueError('CEL shape/depth limit')
    tag=str(node.data); children=node.children
    infer=lambda child:check_type(child,depth+1)
    if tag=='ident':
        name=str(children[0])
        if name not in TYPES: raise ValueError('unknown CEL variable')
        return TYPES[name]
    if tag=='literal':
        token=children[0]
        types={'STRING_LIT':str,'INT_LIT':int,'BOOL_LIT':bool}
        if token.type not in types: raise ValueError('unsupported CEL literal')
        return types[token.type]
    if tag in {'conditionalor','conditionaland'} and len(children)==2:
        if any(infer(c)!=bool for c in children): raise ValueError('CEL boolean operand required')
        return bool
    if tag=='relation' and len(children)==2:
        operator=children[0]
        if str(operator.data) not in {'relation_eq','relation_ne','relation_lt','relation_le','relation_gt','relation_ge'}:
            raise ValueError('unsupported CEL comparison')
        left,right=infer(operator.children[0]),infer(children[1])
        if left!=right or (str(operator.data) not in {'relation_eq','relation_ne'} and left not in {int,str}):
            raise ValueError('CEL comparison type mismatch')
        return bool
    if tag=='unary' and len(children)==2 and str(children[0].data)=='unary_not':
        if infer(children[1])!=bool: raise ValueError('CEL not requires boolean')
        return bool
    wrappers={'expr','conditionalor','conditionaland','relation','addition','multiplication','unary','member','primary','paren_expr'}
    if tag in wrappers and len(children)==1: return infer(children[0])
    raise ValueError('CEL subset excludes calls, macros, arithmetic, lists and object traversal')


@dataclass(frozen=True)
class Policy:
    version: str
    rules: tuple

    @classmethod
    def parse(cls,text: str):
        if len(text.encode())>32768: raise ValueError('policy file too large')
        if any(isinstance(t,(AliasToken,AnchorToken)) for t in yaml.scan(text)):
            raise ValueError('YAML aliases/anchors are forbidden')
        document=PolicyDocument.model_validate(yaml.load(text,Loader=UniqueSafeLoader))
        if len({r.id for r in document.rules})!=len(document.rules): raise ValueError('duplicate rule ID')
        environment=celpy.Environment(annotations={k:CEL_TYPES[v] for k,v in TYPES.items()})
        compiled=[]
        for rule in document.rules:
            tree=environment.compile(rule.expression)
            if len(list(tree.iter_subtrees()))>180 or check_type(tree)!=bool:
                raise ValueError('CEL rule must be a bounded boolean expression')
            compiled.append((rule,environment.program(tree)))
        return cls(digest(document.model_dump()),tuple(compiled))

    def evaluate(self,context: dict,write: bool):
        # Original hard authorization floor: supported writes can never become pass.
        outcome='need_approval' if write else 'pass'; hits=[]
        rank={'pass':0,'need_approval':1,'block':2}
        if set(context)!=set(TYPES) or any(type(context[k])!=t for k,t in TYPES.items()):
            return 'block',['policy_context_invalid']
        if any(isinstance(v,str) and len(v)>128 for v in context.values()):
            return 'block',['policy_context_invalid']
        activation={key:CEL_TYPES[TYPES[key]](value) for key,value in context.items()}
        for rule,program in self.rules:
            try:
                value=program.evaluate(activation)
                if not isinstance(value,celtypes.BoolType): raise ValueError('unknown CEL result')
            except Exception:
                return 'block',['policy_evaluation_error']
            if value:
                hits.append(rule.id)
                if rank[rule.decision]>rank[outcome]: outcome=rule.decision
        return outcome,hits


class PolicyManager:
    def __init__(self,path: Path | None):
        self.path,self.lock=path,RLock()
        self.active=Policy.parse(path.read_text(encoding='utf-8') if path else 'version: builtin-v1\nrules: []\n')

    def reload(self):
        if self.path is None: raise ValueError('no configured policy file')
        replacement=Policy.parse(self.path.read_text(encoding='utf-8'))
        with self.lock: self.active=replacement
        return replacement.version
