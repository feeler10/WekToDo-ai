'''Backward-compatible imports for the migrated intent contract.'''

from app.intent.contracts import IntentClassifier
from app.intent.enums import IntentType as TaskIntent
from app.intent.models import IntentResult as IntentClassification

__all__ = ['IntentClassification', 'IntentClassifier', 'TaskIntent']
