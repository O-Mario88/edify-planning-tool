import { Module } from '@nestjs/common';
import { PlReviewService } from './pl-review.service';
import { PlReviewController } from './pl-review.controller';

@Module({
  controllers: [PlReviewController],
  providers: [PlReviewService],
})
export class PlReviewModule {}
